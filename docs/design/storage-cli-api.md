# Cherries 新存储模型、CLI 与 Python API

状态：v5 存储与接口规范，2026-11-08。实现位于 `liblaf.cherries.store`；
使用方式以 [用户文档](../README.md) 为准。

依据：[实验记录存储结构设计](<t3-thread://v2/f1505dfa-d831-4ffa-9c90-5e80a8372a4c/199a4483-abab-4560-9e78-bca80ca68963>)
的最终目录方案及后续修正。改造前的实现核对到提交
`d04abd42cf7b00a504ebc2de3d3b9d6d25f2eb96`。

配套说明：[详细存储结构与工作流](storage-workflow.md)。

本提案按单用户、串行修改存储设计。一次实验可以使用自己的计算线程和进程；
指标文件由一个 writer 写入，保存前由实验程序结束所有产物写入。

## 1. 当前实现的判断

改造前 Cherries 有可复用的 CAS、文件校验、普通文件物化、来源绑定和源码采集能力，
但不能直接读写参考线程确定的新格式。NAS 上的格式转换与当前 Python recorder
是两条不同的写入路径；迁移产生新目录，并不表示 recorder 已支持这些目录。

| 需求 | 当前实现 | 新契约 |
| --- | --- | --- |
| 所有项目共享 CAS | collection 内去重，默认按项目选择 collection | 一个 Store 包含多个 Project，共享对象空间 |
| 带后缀的对象 | `objects/sha256/ab/<digest>` | `objects/sha256/ab/cd/<digest>.<ext>` |
| 人可读的 run 文件夹 | 不可变 JSON record、独立工作目录与可选物化视图 | `projects/<id>/runs/<uuid>/run.yaml` 为正式记录 |
| 结束后追加文件和报告 | notes/labels 事件，analysis 另存 record | 同一个 Run 支持受控编辑 |
| 可直接打开的报告 | 报告通常属于待物化的内容 | README、reports、assets 保留普通文件 |
| Git 持久快照 | HEAD、patch、选定 untracked；重放依赖原仓库 | bare 仓库保存真实结束 ref、Git 对象及所需 LFS |
| 指标 | 内存积累，结束写 JSON 数组 | 运行中 JSONL，结束写 Parquet |
| 快速组合查询 | 遍历记录过滤；`index.json` 仅记录 root digest | 本机可重建 SQLite 索引 |
| run ID | UUIDv4 | 新 run 使用 UUIDv7；旧 ID 保留 |
| 删除与回收 | 旧 collection 的 pause/discard/prune 协议 | 按新目录、来源引用及全 Store 对象图回收 |

代码依据：[`Store`](../../src/liblaf/cherries/records/_store.py)、
[`Run`](../../src/liblaf/cherries/core/_run.py)、
[`capture_source`](../../src/liblaf/cherries/_capture.py)、
[`MetricsManager`](../../src/liblaf/cherries/core/metrics/_manager.py)、
[`CLI`](../../src/liblaf/cherries/_cli.py)。用户契约以
[`docs/README.md`](../README.md) 为准。

## 2. 对外的四个对象

- **Store**：一个文件系统根目录，拥有共享 CAS、项目注册表和维护入口。
- **Project**：稳定 project ID 与一个主源码 Git 仓库的绑定。
- **Run**：一次计算、可视化或人工整理，UUID 在创建时确定。
- **File**：run 内的逻辑文件路径；内容可以内联，也可以由 pointer 引用 CAS。

`simulation`、`visualization`、`analysis` 等只是 `kind`。
可视化使用与计算相同的运行、文件、指标、保存和删除接口。

Run 的执行结束后，允许修改名称、标签、说明、报告和附件。执行命令、实际消费的
输入绑定、参数、执行结果、起止时间及结束代码快照作为执行证据固定。
补录材料带有 `attached_at`，不会追认成执行时已使用的输入。重新计算创建新 run。

**建议第一版不实现整个 run 的历史修订系统。**
这是在最终文件夹方案上做出的接口简化：普通编辑覆盖当前记录；来源绑定固定到
消费时的内容摘要、大小和代码 commit，并保留当时所需的小型来源信息。
它能追溯实际输入，但不提供“恢复源 run 当时全部标签与报告”的能力。
若以后需要这种能力，再引入显式的 run snapshot；第一版不提供 `run@revision`。

## 3. 文件布局与权威数据

```text
cherries/
├── store.yaml
├── objects/sha256/ab/cd/<完整 64 位 digest>.<ext>
└── projects/<project-id>/
    ├── project.yaml
    ├── <project-id>.git/                 # 标准 bare Git 仓库
    │   ├── objects/...
    │   ├── refs/runs/<run-id>
    │   ├── lfs/objects/ab/cd/<digest>     # 仓库自己的标准 LFS 实体
    │   └── cherries/submodules/<key>.git/# 各自完整的子模块归档
    └── runs/
        ├── <run-id>.tmp/                 # 准备、运行或尚未完成保存
        │   ├── run.yaml
        │   ├── run.log
        │   ├── metrics.jsonl
        │   ├── inputs/...
        │   ├── outputs/...
        │   └── scratch/...
        └── <run-id>/                     # 已发布、可继续编辑
            ├── run.yaml
            ├── run.log
            ├── metrics.parquet
            ├── inputs/neutral.vtu.lfs
            ├── outputs/result.vtu.lfs
            ├── figs/loss.png.lfs
            ├── assets/loss.png           # 普通文件副本
            ├── reports/details.md
            └── README.html

# 以下是维护辅助文件，不属于用户日常工作目录：
cherries/.cherries/transactions/           # 未完成变更的恢复依据
cherries/.cherries/deletions/              # 最小删除凭据
cherries/.cherries/trash/                  # 尚未完成的删除暂存

# 每台查询机器独立保存，可随时重建：
本机缓存/<store-id>/index.sqlite
本机缓存/<store-id>/files/<digest>/<逻辑路径>
```

权威数据是 `run.yaml`、实际 pointer 文件、内联文件和 Git refs。
`run.yaml` 不再维护一份重复的完整 `路径 → oid/size` 表。
它只保存参数、来源关系、执行信息、文件角色补充、目录/伴随文件分组等语义。
对象摘要和大小从 pointer 读取；来源绑定里的摘要是“曾经消费什么”的证据。

### CAS 与 pointer

- CAS 对象 ID 为 `sha256:<完整摘要>`，摘要始终针对真实文件字节。
- 同一摘要只允许一个正式对象路径。通过摘要定位对象，后缀只用于辨识。
- 后缀取最后一次成功 `put` 的值；读文件、解析 pointer、建立来源绑定不会改后缀。
- 默认取逻辑文件名最后一个 suffix 并转小写，无 suffix 使用 `bin`；复合后缀可显式指定。
- 已知 digest 的临时文件位于正式对象旁：`<digest>.<ext>.tmp`。
  未知 digest 的内容先保留在 run 的 `.tmp` 目录；不另设 `objects/tmp/`。
- `.lfs` 是 pointer 文件的附加后缀。例如逻辑路径 `outputs/a.vtu` 对应
  `outputs/a.vtu.lfs`，内容采用标准三行 Git LFS pointer，末尾有换行。
- 指针生成和严格校验可复用 `git lfs pointer`；这不会自动把实验产物纳入 Git。
- `file add` 识别内容为 pointer 时，解析、查找并校验所指实体；实体不可用就报错。
  不把 pointer 文本再次包成 CAS payload，不根据 `.lfs` 扩展名猜文件内容。
- 零字节实体使用明确的三行、`size 0` 引用；控制目录中的空文件不隐式解释成 pointer。

兼容格式依据：[Git LFS pointer 规范](https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md)。

大数据默认以 pointer 保存到 `inputs/`、`outputs/`、`figs/`；
`run.yaml`、`run.log`、`metrics.parquet`、README、reports 和 assets 是普通文件。
因此复制 run 文件夹即可打开报告；完整恢复计算数据还需要 CAS。
`run export --with-data` 可导出包含全部真实文件的独立目录。

`assets/` 是独立副本，允许与 CAS 重复。替换 figure 后，旧报告素材不会自动改变；
更新报告时显式替换 assets。HTML 的本地相对资源要随报告一起导入，缺失资源报错。

### 目录和伴随文件

目录按文件生成 pointers，保留相对路径；空目录清单放在 `run.yaml` 的文件分组中。
`.series`、纹理目录等使用显式 group 保存必需的伴随文件。
获取 group 中的主文件会恢复整组拓扑，不通过全库搜索猜测附件。
路径必须是 run 内相对路径；导入链接时复制解析后的内容，不在归档中创建链接。

## 4. 元数据与精确来源

```yaml
schema_version: 1
id: 019a6410-7000-7000-8000-000000000001
project: phace-exp
name: smile-baseline
kind: simulation
status: succeeded
created_at: 2026-11-08T12:00:00Z
started_at: 2026-11-08T12:01:00Z
ended_at: 2026-11-08T12:12:00Z
updated_at: 2026-11-08T12:15:00Z
tags: [smile, baseline]
parameters:
  steps: 200
execution:
  argv: [uv, run, python, src/solve.py, --steps, '200']
  exit_code: 0
  observed_by: cli
git:
  ref: refs/runs/019a6410-7000-7000-8000-000000000001
  commit: <完整 Git 对象 ID>
  workspace_head: <原工作区 HEAD>
  source_stable: true
  replay_verified: false
sources:
  - input: inputs/neutral.vtu
    project: capture-data
    run: 019a6400-7000-7000-8000-000000000002
    path: outputs/neutral.vtu
    oid: sha256:<完整摘要>
    size: 123456
    code_commit: <消费时来源 run 的代码 commit>
    bound_at: 2026-11-08T12:01:01Z
metrics:
  loss:
    last: 0.001
    min: 0.001
    max: 1.2
    count: 200
    nonfinite_count: 0
extensions: {}
```

示例中的占位摘要在实际文件中必须替换为完整值。
`schema_version` 属于新的 run schema，不能用于识别旧 collection 格式；
`store.yaml` 另含明确的 `format: cherries-run-store` 和 `format_version`。
YAML 使用保序、安全的读写器，拒绝重复 key，保留未知扩展字段。

FileRef 是不可变值：`project + run + path + oid + size + code_commit + bound_at`。
读取来源时先固定 FileRef 并登记子 run 的 input binding，再物化和消费。
运行中的输入仍是普通文件，完成保存时发布成子 run 自己的 input pointer。
来源后来替换了同名输出，子 run 仍然读取原摘要。摘要相同也不推断两个 run 身份相同。
原始本地文件只有内容身份和原路径记录；没有来源 run 时不编造父记录。
已消费 input 的 pointer 与来源绑定一起固定，不能通过编辑覆盖或删除；
后补 input 使用新路径并标为附件。手工改动导致二者不一致时，校验及 GC 均报错。
尚未绑定到已保存 run 或未发布工作区的 FileRef 值本身不构成永久保留根。

## 5. 生命周期、保存和修改

`run new` 创建 `<uuid>.tmp/`，阶段为 `prepared`。开始执行后进入 `running`，
结束后进入 `finalizing`。只有完成保存才发布为 `<uuid>/`。
正式 run 的 `status` 可以是 `succeeded`、`failed`、`cancelled` 或 `recorded`；
`recorded` 用于未由 recorder 观察执行的材料记录。

一次正常保存依次完成：

1. 结束并关闭产物、日志和指标 writer。
2. 固定结束代码快照，归档必要 Git、子模块和 LFS 内容。
3. 将指标 JSONL 转成临时 Parquet，检查 schema、行数及汇总。
4. 将选定产物写入 CAS，校验后生成 pointers。
5. 写完 `run.yaml` 和普通文件，确认所有引用完整。
6. 刷盘并将 `<uuid>.tmp/` 改名为 `<uuid>/`，完成目录持久化确认。
7. 更新本机索引；索引失败作为可修复警告返回。

保存失败保留 `.tmp` 及原始 JSONL；不得因为 Python 返回成功就报告“已保存”。
发布改名之后若持久化确认失败，返回 `published=true, durability=unconfirmed`，
保留恢复依据。后续清理失败只产生 warning，不撤销已经确认的保存。

执行失败与保存失败分别报告。建议新实验默认 `on_error="keep"`，保存诊断并明确
标为 failed；可以配置 `on_error="discard"` 删除本次未发布工作内容。
失败保存只保留实际存在的产物，并列出未生成的必需输出；
成功执行缺少必需输出则属于保存失败，不能降格成完整的成功 run。
线程中“删除所有失败执行”是那批历史清理的授权，不推断成未来自动丢弃的永久策略。
用户可按 status 筛选并批量删除失败记录。强杀、断电遗留 `.tmp` 需要显式恢复，
不在浏览、打开 Store 或重建索引时自动删除。

`run edit` 和 `Run.edit()` 使用相同的变更事务，只暂存发生变化的文件。
事务写清旧状态、待发布文件和完成标记；正常完成后移除临时内容。
崩溃恢复按日志完成或回退该次变更，不把半次编辑当成完整 run。
存储存在未完成的变更时，相关写入及 GC 先要求恢复。
这是一套串行操作的故障恢复约定，无需多机事件合并或分布式锁协议。

允许直接编辑 YAML、Markdown、HTML 和 assets。随后执行 `run validate` 与
`index refresh`。直接编辑失去应用事务的回退能力；手工改动 pointer 后也必须
重新校验实体。GC 每次重新读权威文件，任何无法解析的记录都阻止回收。

## 6. CLI

全局上下文使用 `--store PATH`、`--project ID`、`--json`。
命令按对象分组，不再引入独立 analysis workspace 和专用分析保存协议。

### 建库与项目绑定

```bash
cherries store init /data/cherries
cherries --store /data/cherries project add phace-exp --repo .
cherries project list
cherries project show phace-exp
```

`project add` 在源码项目的配置中记录稳定 ID，机器本地配置记录 Store 路径。
同一 Git 项目移动路径后仍保持相同 ID；不会根据新绝对路径创建新 collection。

```toml
# cherries.toml，可提交到源码仓库
[project]
id = "phace-exp"

# cherries.local.toml，本机配置
[store]
path = "/data/cherries"

[recording]
on_error = "keep"
metric_durability = "fsync"
```

显式 `--store` 优先于 `CHERRIES_STORE`，再依次读取本机、项目及用户默认配置。
相对路径相对于定义该配置的文件解析。普通查询不会初始化或改写权威存储。

### 执行与手动准备

```bash
# 创建、执行、保存；-- 后是原始命令及参数。
cherries run exec --name smile-baseline --tag smile --tag baseline -- \
  uv run python src/solve.py --steps 200

# 先准备目录、素材和 metadata，再执行。
cherries run new --name smile-baseline --kind simulation
cherries file add <run-id> neutral.vtu --as inputs/neutral.vtu
cherries run exec <run-id> -- uv run python src/solve.py --steps 200

# 可视化或后续计算：在消费前绑定来源文件及当时的摘要。
cherries run new --name smile-view --kind visualization
cherries file add <view-run-id> --from-run <source-run-id> \
  --from-project phace-exp --path outputs/result.vtu --as inputs/result.vtu
cherries run exec <view-run-id> -- uv run python src/render.py

# 人工整理已有材料：不伪造程序执行成功。
cherries run new --name archived-measurement --kind dataset
cherries file add <run-id> measured.vtu --as outputs/measured.vtu
cherries run save <run-id> --status recorded

# 处理意外中断留下的现场。
cherries run recover <run-id>
cherries run save <run-id> --status cancelled
```

`run exec` 默认保持源码项目的 cwd，通过 `CHERRIES_RUN_DIR` 和
`CHERRIES_RUN_ID` 向程序提供工作目录及身份，并记录 stdout/stderr 到 `run.log`。
程序可使用 Python API 获取路径，也可直接写这些普通目录。
普通目录写入通过角色目录发现；`scratch/` 排除。所需输出声明仍可检查遗漏。
对 prepared run 的 `file add` 保留普通工作文件，入库前不会把程序需要读取的内容
替换成 pointer。执行开始时固定预先登记的输入；执行后补录的材料不会成为消费证据。

外层 `run exec` 与内层 `cherries.run()` 协作使用同一个 run。
外层控制器拥有执行结果和最终发布；内层负责注册文件、指标和参数，不再次保存。
附着 run 时若传入冲突的 project、kind 或参数，应报错。

`run recover` 只核对和恢复保存现场，不自动重启科学计算。
恢复计算必须由应用读 checkpoint，并创建带来源的新 run。
`file add --from-run` 在执行命令前解析并固定 FileRef；省略 `--from-project` 时
使用当前项目。为 prepared run 绑定时保存来源和输入实体，执行开始时标记消费。
为已结束 run 添加时只记为后补附件；`--source-run` 的重跑关系不代替具体输入绑定。

### 查询、报告与文件

```bash
cherries run list --tag smile --status succeeded \
  --where 'metrics["loss"].last < 0.01' --sort=-started_at --limit 20
cherries --json run show <run-id>
cherries run list --all-projects --kind visualization

cherries run tag add <run-id> weekly
cherries run tag remove <run-id> baseline
cherries run edit <run-id>                  # 编辑暂存的 run.yaml
cherries report edit <run-id> README.md     # $EDITOR 编辑后发布
cherries report add <run-id> report.html --as README.html --assets ./assets
cherries file add <run-id> loss.png --as figs/loss.png
cherries file remove <run-id> figs/obsolete.png

cherries file list <run-id>
cherries file path <run-id> outputs/result.vtu
cherries file get <run-id> outputs/result.vtu --to ./result.vtu
cherries run export <run-id> --to ./exported-run --with-data

cherries metrics show <run-id> --name loss
cherries metrics export <run-id> --to ./metrics.csv
cherries run validate <run-id>
cherries index refresh
cherries index rebuild
```

`file path` 输出带原逻辑文件名的稳定本机副本路径；`file get` 复制到指定目标。
二者不会把可改名的 CAS 路径作为日常读取接口。
已发布 run 的 `.directory` 可直接查看报告，数据文件通过 File API 解析。

查询语法只允许已定义的字段、比较和布尔运算，不执行 Python 或任意 SQL。
`--tag` 多次指定表示全部满足。跨项目查询返回 project ID。
JSON 输出使用固定版本 envelope，诊断和日志输出到 stderr。

### 代码、删除与维护

```bash
cherries code show <run-id>
cherries code checkout <run-id> --to ./replay-code
cherries project verify phace-exp --git --lfs --offline

cherries run delete <run-id> --dry-run
cherries run delete <run-id>
cherries run delete --status failed --dry-run
cherries run delete --status failed
cherries store gc --dry-run
cherries store gc
cherries store verify --metadata
cherries store verify --objects
cherries store recover
```

`code checkout` 只准备源码；执行仍由用户明确发起，不承诺重放验证。
新运行可以通过 `--source-run <id>` 记录重跑关系。

### 本地到归档盘的增量复制

```bash
cherries run copy <run-id> --to-store /mnt/DATA41-Users2/liqin/cherries
cherries run copy <run-id-1> <run-id-2> --to-store /archive/cherries
```

`run copy` 复制选定 run 及其来源闭包：先复制和校验缺少的 CAS 实体、代码闭包、
LFS，再发布目标 run 目录。目标已有相同实体时复用；源 run 与目标 run 内容一致则跳过。
同 UUID 的可变记录内容不一致时返回冲突和差异，不能按 mtime 或“最后同步”静默覆盖。
显式 `--replace --expect <目标记录 fingerprint>` 才替换已检查的目标版本。
替换仅允许可变描述和附件差异；同 UUID 的执行命令、参数、结果、代码 commit
或已消费来源绑定不同，属于身份冲突，必须拒绝。已存在的 `refs/runs/<id>`
必须指向相同 commit；报告更新不能移动它。
复制保留目标其他 refs，不继承来源机器的绝对路径配置。
`copy` 不删除本地数据；返回逐 run 的目标校验凭据，源端清理仍通过独立删除与 GC。
第一版以可访问的普通文件系统路径为传输接口，包括挂载的 NAS。

## 7. Python API

核心 API 为显式对象；顶层便捷函数解析配置后调用相同实现。

```python
from liblaf import cherries

with cherries.run(
    name="smile-baseline",
    kind="simulation",
    parameters={"steps": 200},
    tags=["smile", "baseline"],
) as run:
    mesh = run.input("/data/neutral.vtu", name="neutral.vtu")
    result = run.output("result.vtu")
    # solve(mesh, result)
    run.log_metrics({"loss": 0.001, "grad_norm": 0.02}, step=200)

    figure = run.figure("loss.png")
    # plot_loss(figure)
    run.asset("loss.png", source=figure)
    run.report("README.md").write_text("# Smile\n\n![Loss](assets/loss.png)\n")

# 这里返回后运行结束；未附着 CLI 时，context 负责保存。
print(run.result.run_id, run.result.saved)
```

`input()` 返回独立普通文件路径；`output()`、`figure()` 声明所需产物并返回待写路径。
`asset()` 复制一份实际素材；`report("README.md")` 指向根 README，其他名称默认放
`reports/`，HTML 同理。`run.scratch(name)` 返回不保留的路径。
没有活动 context 时，这些 helper 直接报错。context 退出后，原工作路径不再作为
稳定 API；后续从保存结果取得 Run，再通过 File API 打开数据。

```python
store = cherries.Store.open("/data/cherries")
project = store.projects.get("phace-exp")
saved = project.runs.get("<run-id>")

# FileRef 在此时固定内容身份，而非执行时再跟随父 run 的最新路径。
source = saved.file("outputs/result.vtu").ref()

with project.run(name="smile-view", kind="visualization") as view:
    mesh = view.input(source, name="result.vtu")
    image = view.figure("front.png")
    # render(mesh, image)

with saved.edit() as edit:
    edit.tags.add("weekly")
    edit.add_file("./loss.png", path="figs/loss.png")
    edit.asset("loss.png", source="./loss.png")
    edit.report("README.md").write_text("# Updated findings\n")

local_path = saved.file("outputs/result.vtu").materialize()
saved.file("outputs/result.vtu").copy_to("./result.vtu")
curves = saved.metrics.scan()               # Polars LazyFrame
rows = project.runs.query(
    tags=["smile"],
    status="succeeded",
    where='metrics["loss"].last < 0.01',
    sort="-started_at",
    limit=20,
)
```

建议的 public signatures：

```python
Store.open(path) -> Store                   # 只打开，不隐式初始化/清理
Store.create(path) -> Store
Store.projects.add(id, *, repo) -> Project
Store.projects.get(id) -> Project
Store.gc(*, dry_run=True) -> GCResult
Store.verify(*, objects=False) -> VerificationResult

Project.run(*, name, kind="simulation", parameters=None, tags=(),
            on_error=None) -> RunContext
Project.runs.create(*, name, kind="record") -> DraftRun
Project.runs.get(id) -> Run
Project.runs.query(...) -> list[RunSummary]
Project.runs.delete(ids, *, dry_run=True) -> DeletionResult

DraftRun.execute(argv, *, cwd=None) -> RunResult
DraftRun.save(*, status="recorded") -> RunResult
Run.edit() -> RunEditorContext
Run.file(path) -> RunFile
Run.export(destination, *, with_data=False) -> Path
Run.copy_to(target_store, *, replace=False, expected_target=None) -> CopyResult
RunFile.ref() -> FileRef
RunFile.materialize() -> Path
RunFile.copy_to(destination) -> Path
```

`RunResult` 至少包含 `run_id`、`directory`、`execution_status`、`exit_code`、
`saved`、`published`、`durability` 和 `warnings`。
CLI 返回过程退出状态；Python 异常保留原始实验异常及其录制结果。
纯 Python 代码支持可注入的 Store，不需要替换全局 singleton 才能测试。

## 8. 指标与索引

指标长表固定为 `name: String, step: Int64?, timestamp_ms: Int64, value: Float64`。
**不增加 seq。** timestamp 允许重复，step 允许重复或为空；不把其中任何组合设为唯一键。
行序保留追加顺序，相同 timestamp 时不宣称存在可靠的时间先后。

每次 `log_metric` 追加一行 JSONL；`log_metrics` 为每个指标追加一行，使用相同 timestamp。
默认 `metric_durability="fsync"`，返回前 flush + fsync，满足逐次持久化要求。
可显式选择 `flush` 以降低每条指标的 I/O 成本；其含义是立即可见而非断电持久化。
内存只保存小型摘要，不保存完整历史。

JSONL 中非有限值使用 `"NaN"`、`"Infinity"`、`"-Infinity"`；转换时还原 Float64。
Parquet 封存以固定 schema 流式完成，空指标不生成文件。
截断的末行只在恢复流程中单列和处理，正常结束时视为错误，不静默丢行。
记录数、非有限值数和摘要一致后才删除原始 JSONL。
`last` 以追加顺序确定，`min/max` 仅统计有限值；`count` 包含全部值，
`nonfinite_count` 单列。非有限的 last 不参与普通数值筛选。

实现基础：[Polars scan_ndjson](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_ndjson.html)、
[sink_parquet](https://docs.pola.rs/api/python/stable/reference/api/polars.LazyFrame.sink_parquet.html)。

SQLite 缓存只在查询机器本地，索引 runs、tags、typed parameters、metric summaries、
文件摘要及来源边。API/CLI 修改后增量更新对应 run。
手工修改后，`index refresh` 枚举控制文件并比较内容 hash；mtime/size 只能辅助加速。
默认快速查询标注最后刷新时间，`run list --refresh` 先刷新再查询。
索引可以删除重建，不参与发布判定和 GC 可删性判定。

## 9. 源码与自包含 Git/LFS

结束时通过独立索引构造实际工作树的源码快照，包括跟踪文件的修改/删除、
已暂存的新文件、未忽略的新文件。包含范围由项目 source 配置确定并先预览，
禁止运行产物进入源码快照。不能继续使用当前仅按少数扩展名选择 untracked 的规则。

工作树干净时引用已有 HEAD；有变化时生成快照 commit。将必要对象复制或 fetch 到
项目 bare 仓库后，创建固定 `refs/runs/<id>`；`run.yaml` 记录完整 commit ID。
后续标签和报告编辑不移动此 ref，也不修改用户的分支、index 或原 HEAD。
机制可用 [commit-tree](https://git-scm.com/docs/git-commit-tree) 和
[update-ref](https://git-scm.com/docs/git-update-ref) 实现。

子模块递归快照，父快照的 gitlink 指向实际子快照；子仓库及其 LFS 必须放在项目归档中。
外部 editable 源码依赖也需要显式登记，不把“机器上恰好存在”当作已归档。
开始和结束均记录 fingerprint，`source_stable` 只代表这两个边界的观察一致。
结束快照不能证明 Python 之前已经 import 的字节，`replay_verified` 不自动变成 true。

自包含范围为归档内所有保留 refs 的 Git 可达闭包及其中 LFS pointer 引用的实体。
Git 对象不使用 alternates 或浅克隆依赖；LFS 使用 bare 仓库自身默认的
`lfs/objects/ab/cd/<digest>`，不配置指向外部 CAS 的 `lfs.storage`。
归档应能整体移动后仍恢复，不能含依赖旧机器绝对路径的对象存储配置。

**独立仓库的 LFS 实体与实验 CAS 可能各存一份。**
这来自“标准、自包含、可独立搬走”和“不使用链接”的约束。
不能同时承诺这些约束及跨 Git/LFS/CAS 的唯一物理副本。
实验之间仍由共享 CAS 去重；新运行产物不进入 Git/LFS。

离线验收不仅检查文件存在：在原源码仓库和历史网络端点不可访问时，fetch 精确
run ref，恢复 Git、子模块及 LFS，校验工作树文件。
检出工具显式覆盖历史 `.lfsconfig` 的旧端点，使用归档的本地 LFS 来源；
不会重写历史提交。裸库存在 LFS 对象并不意味着任意默认 clone 都会取到自定义
`refs/runs/*`、改写子模块 URL 或忽略历史端点。
Git LFS 的本地 `file:///` 支持来自
[standalone-file](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-standalone-file.adoc)。

## 10. 删除与回收

`run delete` 先校验选择集：活动 run、未完成事务或选择集外保留 run 的来源依赖
会阻止删除。批量删除时，将整批作为选择集检查，因此可一起删除父子失败实验。
第一版不提供强制留下断裂来源链的选项。

删除事务移走 run 目录并移除应用拥有的 `refs/runs/<id>`，保留最小删除凭据。
删除成功之后，这批 run 的 pointers 退出 CAS 保留集合。
删除暂存目录清理失败时返回实际占用和 warning，可恢复继续；不谎报已释放空间。

`store gc` 遍历全部项目的权威文件，计算：

```text
保留对象 = 保留正式 run 的 pointers
         ∪ 受保护的未发布工作及事务引用
         ∪ 已登记的保全/迁移引用
可回收对象 = CAS 中正式对象 − 保留对象
```

存在运行、未核对的 `.tmp`、无法解析的 pointer、未知保全材料或未完成事务时先拒绝 GC。
来源输入本身持有子 run 的 pointer，不依赖可变父输出为它保留字节。
读取通过普通副本，日常不需要读者 lease 或手动 release；尚未复制完的操作属于活动操作。

dry-run 显示 run 目录逻辑字节、CAS 独占字节、共享保留字节、报告副本占用和阻塞原因。
实际回收不使用过期 SQL 索引，也不把“旧文件 hash 字段还存在”自动解释为保留根。
已有迁移的保全清单必须先登记或由专用 reader 识别；未知内容不能当作垃圾。

全局 CAS GC 不操作各 bare 仓库的 LFS 或 Git 对象。
删除实验 ref 后，其他 Git refs 或祖先历史仍可能保留代码及 LFS；
Git/LFS 的独立回收必须按每个自包含仓库的完整保留闭包另行计划。
空间报告分开列出这些范围。

## 11. 实施顺序与验收

建议作为新的主版本实现，先完成一个纵向流程，再扩充功能：

1. 新 schema reader/writer、Store/Project 注册、真实 blob + pointer、UUIDv7、
   普通文件读取、最小保存与恢复；实现 `run exec` 和 Python context。
2. 结束 Git ref、子模块与离线 LFS 闭包；JSONL → Parquet；追加文件和报告；
   本机索引及组合查询。
3. 依赖检查、删除与全库 GC；对旧 recorder collection 和已迁移目录的专用导入。

`run copy` 在本地端到端流程稳定后接入同一 reader/writer 与校验闭包，
不得另写一条仅搬运目录、缺少代码或来源对象的发布路径。

新格式与旧 `collection.json/records/metadata/events` 显式识别。
不让旧 Store 在新目录上初始化，也不悄悄把现有路径改解释为新格式。
旧 `main/log_metric` 等可有薄适配层；旧存储协议不混入新模型。
迁移保留原 run ID、真实角色和来源证据，执行状态未知时保留未知；
导入同内容不能合并身份。迁移与当前 NAS 任务保持独立的发布与验收范围。

实施验收覆盖以下行为，对应 `tests/test_v5_*.py`：

- 两个项目写相同内容但不同后缀，CAS 仅有一个实体，旧 pointer 仍可读。
- pointer 传入 `file add` 后得到真实 payload；缺少实体明确报错。
- 复制 run 文件夹后，README/HTML 和本地素材可直接打开。
- 可视化消费父输出后替换父输出，子 run 的读取内容保持不变。
- 成功、失败、取消、录制失败各有准确状态；未发布现场不被初始化清理。
- 杀进程后恢复 JSONL；同 timestamp、重复 step 与非有限值能正确转换和汇总。
- 保存/编辑各发布边界发生错误时，可区分未发布、已发布未确认、已保存但清理失败。
- 原工作区 index/HEAD 不变；移走原仓库并禁网后仍可恢复 run 代码、子模块及 LFS。
- 删除一个项目的 run 不损坏其他项目；选择集外的来源依赖阻止删除。
- 删除并重建 SQLite 索引不改变记录；陈旧索引和未知材料不能导致 GC 误删。

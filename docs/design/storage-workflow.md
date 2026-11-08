# Cherries 详细存储结构与工作流

状态：v5 存储与工作流规范，2026-11-08。CLI 和 Python API 已实现；
旧格式导入保留来源证据，不推断其执行代码可恢复。
接口完整清单见 [storage-cli-api.md](storage-cli-api.md)。
本文展开文件在运行、保存、修改、复制和回收中的变化。

## 1. 工作区、Store 与归档位置

一个项目有开发工作区和记录库两种目录。

```text
phace-exp/                             # 开发工作区：普通 Git 仓库
├── .git/
├── .gitignore
├── cherries.toml                      # 稳定 project ID、录制策略
├── cherries.local.toml                # 本机 Store 路径，通常 Git ignore
├── pyproject.toml
├── uv.lock
├── src/                              # 实验与可视化脚本
├── configs/
└── libs/                             # 子模块或显式登记的源码依赖

/data/cherries/                        # 本机 Store
├── store.yaml
├── objects/                          # 所有项目共用
└── projects/
    ├── phace-exp/
    └── another-project/

/mnt/DATA41-Users2/liqin/cherries/       # 另一个 Store，可作归档目的地
├── store.yaml
├── objects/
└── projects/...
```

代码、配置和锁文件在开发工作区编辑；一次执行的输入副本、输出、日志、指标和
报告写入 Store 中的 run 目录。源码目录不会随着每次运行复制一份大数据。

同一 Store 的项目共享 CAS。另一个 Store 是独立副本，需要自己的实体才能独立恢复；
本机与 NAS 之间的复制不能算作一份物理存储。
项目 ID 和 run ID 跨 Store 保持不变；两个独立初始化的 Store 各有自己的 store ID。
整个 Store 搬到新路径时保留其 ID。

`cherries.local.toml` 中的路径只用于当前机器定位，不写入可搬迁记录的内容引用。

## 2. 一个 Store 的完整结构

```text
cherries/
├── store.yaml
├── objects/
│   └── sha256/
│       └── ab/
│           └── cd/
│               ├── <完整 digest>.vtu
│               └── <另一个 digest>.png
├── projects/
│   └── phace-exp/
│       ├── project.yaml
│       ├── phace-exp.git/                 # 标准 bare Git 仓库
│       │   ├── HEAD
│       │   ├── config
│       │   ├── objects/...
│       │   ├── refs/...
│       │   ├── lfs/objects/ab/cd/<digest>
│       │   └── cherries/submodules/<key>.git/
│       └── runs/
│           ├── <UUIDv7>.tmp/               # 尚未完成保存
│           └── <UUIDv7>/                   # 正式记录
└── .cherries/                             # 内部恢复与维护信息
    ├── transactions/
    ├── deletions/
    └── trash/

本机缓存/<store-id>/
├── index.sqlite
└── files/<digest>/<原逻辑路径>
```

这里的 `ab/cd` 是 SHA-256 的前四位；文件名中的完整 digest 仍包含这四位。
CAS 文件里是原始 payload，逻辑文件名、角色和报告路径不参与内容摘要。

### Store 与 Project 元数据

`store.yaml` 至少记录：

```yaml
format: cherries-run-store
format_version: 1
id: <store UUID>
created_at: 2026-11-08T12:00:00Z
```

`project.yaml` 至少记录稳定 ID、显示名称、创建时间、源码归档的相对位置，
以及归档内各源码仓库的标识。开发工作区的本机绝对路径属于本机配置。

```yaml
schema_version: 1
id: phace-exp
name: Facial physics experiments
created_at: 2026-11-08T12:00:00Z
code:
  repository: phace-exp.git
```

每个 run 的 Git 元数据再固定主仓库及子仓库的实际 commit 和路径映射。
裸库内 refs 可能由 Git 打包到 `packed-refs`；工具通过 Git 读取，不假定一定存在
一个同名的 loose ref 文件。

## 3. 一个 run 中保存什么

正式目录示例：

```text
projects/phace-exp/runs/<run-id>/
├── run.yaml                         # 名称、执行证据、标签、来源、指标摘要
├── run.log                          # 可直接阅读的执行日志
├── metrics.parquet                  # 指标长表，可选
├── inputs/
│   └── neutral.vtu.lfs
├── outputs/
│   ├── result.vtu.lfs
│   └── checkpoints/
│       └── final.npz.lfs
├── figs/
│   └── loss.png.lfs
├── assets/
│   └── loss.png                     # 报告使用的实际图片
├── reports/
│   └── comparison.md
└── README.html                      # 默认报告入口，也可用 README.md
```

| 项目 | 存放内容 | 如何使用 |
| --- | --- | --- |
| `run.yaml` | 参数、命令、时间、状态、Git commit、来源、标签、摘要 | 查看、筛选和追溯 |
| `run.log` | 日志文本 | 直接打开 |
| `metrics.parquet` | 完整指标历史 | Polars 等表格工具读取 |
| `inputs/` | 输入文件的标准 `.lfs` pointers | API/CLI 解析为实际文件 |
| `outputs/` | 输出、选择保留的 checkpoint 的 pointers | 同上 |
| `figs/` | 图片、渲染结果等 pointers | 同上 |
| `assets/` | 随报告携带的实际素材 | 报告用相对路径直接引用 |
| `reports/`、README | 普通 Markdown、HTML 及报告文件 | 直接打开 |

`metrics.parquet`、日志和报告默认不走 CAS，因此能直接阅读和分析。
CAS 主要消除输入、输出、checkpoint、图像等大文件在各 run 之间的重复。

`run.yaml` 不复制一份完整文件 manifest。当前文件的 oid 和 size 由 pointer 决定；
来源绑定中保留 oid、size，是为了固定执行时的输入证据。
空目录与伴随文件的分组信息保存在元数据中。

### Pointer 的例子

逻辑文件名为 `outputs/result.vtu`，磁盘上的引用文件是 `outputs/result.vtu.lfs`：

```text
version https://git-lfs.github.com/spec/v1
oid sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789
size 123456
```

实际内容在：

```text
objects/sha256/ab/cd/abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789.vtu
```

相同字节后来作为 `.bin` 成功入库，可以将 CAS 对象改名为 `<digest>.bin`。
旧 pointer 无需修改，因为它通过摘要查找内容。
pointer 格式只是实验库使用的引用表示；实验输出不因此进入 Git 历史。
Git 源码树内历史 LFS pointer 仍由 Git/LFS 处理。

### 报告素材为什么另存

`figs/loss.png.lfs` 用于归档和溯源，`assets/loss.png` 用于报告直接显示。
二者可以有相同字节，但 assets 是独立的实际副本。

```markdown
![Loss](assets/loss.png)
```

根 README 可以这样引用。位于 `reports/` 的报告则使用 `../assets/loss.png`，
或携带自己的相对资源目录。导入报告时保留并校验这套相对路径关系。
后续替换 figs 中的对象，不会自动改变 assets。

## 4. 输入何时固定

需要区分三种情况。

1. **执行前准备输入。** `file add --from-run` 立即解析来源并固定内容，准备普通
   输入副本；执行开始时将其标为预先登记的输入。
2. **运行中读取新输入。** `run.input()` 在返回路径前完成绑定和物化。程序取得
   路径后才读取数据；不要求所有动态输入都在运行开始前已知。
3. **执行结束后补录。** 后补的输入或输出是附件，记录其真实添加时间和来源，
   不改写原执行曾消费哪些内容的证据。

来源绑定包含：

```text
来源 project + 来源 run + 来源逻辑路径
+ SHA-256 + size + 来源代码 commit + 绑定时间
```

运行期间 `inputs/neutral.vtu` 是独立的普通文件。绑定信息先写入 run 的执行证据，
保存时再生成该 run 自己的 `inputs/neutral.vtu.lfs`。
输入副本不允许在计算中修改；保存前核对字节，变化时保留现场并报录制错误。

来源 run 后来替换同名输出，已经绑定的子 run 继续引用旧摘要。
只在内存中创建一个 FileRef 不会永久保留数据；它需要绑定到 run 或未发布工作中。

预先登记或通过 helper 绑定，能说明“这个输入交给了执行程序”；
它不构成对程序内部每一次实际文件读取的监控。

## 5. 从创建到保存

### 第一步：创建 UUID 工作目录

```bash
cherries run new --name smile-baseline --kind simulation
```

创建 `<run-id>.tmp/`，写入初始 `run.yaml`，为准备材料提供稳定身份。
此时可以放入输入、配置说明和初稿报告。
源码仍在项目的 Git 工作区开发。

### 第二步：执行

```bash
cherries run exec <run-id> -- uv run python src/solve.py --steps 200
```

也可以直接 `run exec --name ... -- COMMAND`，由它自动完成第一步。

执行 cwd 默认是源码项目目录。环境变量及 Python Run 对象提供 `.tmp` 目录，
输出通过返回的绝对路径写入该目录；不要求程序切换 cwd。

运行中的目录示例：

```text
<run-id>.tmp/
├── run.yaml
├── run.log
├── metrics.jsonl
├── inputs/neutral.vtu              # 真实输入副本
├── outputs/result.vtu              # 程序正在写的真实文件
├── figs/loss.png                   # 实际图片
├── assets/loss.png                 # 报告素材副本
├── README.md
└── scratch/solver-cache/...        # 不保留的临时内容
```

Run helper 注册产物；普通程序也可以直接写这些角色目录，保存时扫描选择保留的文件。
输出声明用于检查预期文件是否缺失。程序需结束自己的线程、子进程和异步写入后再返回。

### 第三步：追加指标和日志

`run.log` 持续写入；指标逐条写 `metrics.jsonl`：

```json
{"name":"loss","step":200,"timestamp_ms":1794139200000,"value":0.001}
```

指标字段为 `name, step, timestamp_ms, value`，不含 seq。
同 timestamp 或 step 的多条记录全部保留，不去重。
默认每次记录调用返回前 flush + fsync；可显式选 `flush`，减少 I/O 成本。
内存只维护指标的小型摘要。

### 第四步：结束并保存

所有文件停止写入后，按以下顺序完成：

1. 记录执行结果和结束时间，关闭 writer。
2. 捕获结束源码，保存真实 Git commit 与固定 ref。
3. 将 JSONL 流式转成临时 Parquet，检查 schema、行数和指标摘要。
4. 将 inputs、outputs、figs 中的保留文件写入 CAS，并校验内容。
5. 用 `.lfs` pointer 替换工作目录中的对应真实数据副本。
6. 写完 `run.yaml`、日志、报告及素材，检查全部引用，将 scratch 移入事务清理区。
7. 确认落盘，将 `<run-id>.tmp/` 改名为 `<run-id>/` 并确认发布持久性。
8. 清理事务中的 scratch、已成功转换的 JSONL 等临时内容，更新本机索引。

被替换的工作数据副本必须在对应 CAS 实体完成校验后才可移除。
`scratch/` 在发布前移出 run 目录；若随后删除临时内容失败，残留明确列入保存结果
和后续恢复信息。发布前移动 scratch 失败时，仍保留工作目录并报告未完成保存。

同一个文件的变化为：

```text
运行中：runs/E.tmp/outputs/result.vtu       实际字节
保存后：runs/E/outputs/result.vtu.lfs       pointer
        objects/sha256/ab/cd/<digest>.vtu  实际字节
读取时：本机缓存/.../outputs/result.vtu     独立实际副本
```

原工作路径在保存后可能消失或发生改名；后续读取通过 saved Run 的 File API 获取。

### 结束源码如何保存

每个 run 的结束 ref 为 `refs/runs/<run-id>`。
工作区干净时指向原 HEAD；有变化时通过独立索引生成包含源码变化的快照 commit。
保存跟踪文件修改/删除及选定的未忽略新源码，不改变开发工作区的分支或 index。

主仓库 Git 对象、子模块快照及所需 LFS 字节都归档到项目的 bare 仓库范围内。
父快照 gitlink 必须指向实际子快照，检出工具使用归档中的路径映射恢复子模块。
归档后的报告编辑不移动这个结束 ref。

源码状态的开始/结束比较只提供边界证据；保存结束代码不等于已经验证计算可重放。

### 失败和中断

| 情况 | 执行结果 | 记录结果与目录 |
| --- | --- | --- |
| 执行成功且保存完成 | succeeded | 正式 UUID 目录 |
| 执行报错且诊断保存完成 | failed | 正式 UUID 目录 |
| 取消且现场保存完成 | cancelled | 正式 UUID 目录 |
| 人工材料记录 | 未观察执行 | recorded，正式 UUID 目录 |
| 执行成功但保存失败 | succeeded | 未完成保存，保留 `.tmp` |
| 强杀、断电 | 待核对 | 保留 `.tmp` 和恢复依据 |

`.tmp` 表示尚未完成保存，不能用于表示所有失败实验。
新运行建议默认保留失败诊断；是否丢弃未发布 payload 由明确策略决定。
恢复命令修复保存现场，不自动重启 solver。

## 6. 保存以后如何使用

### 查询与读取

```bash
cherries run list --tag smile --status succeeded
cherries run show <run-id>
cherries file path <run-id> outputs/result.vtu
cherries file get <run-id> outputs/result.vtu --to ./result.vtu
```

报告、日志、指标可在正式 run 目录直接打开。
pointer 数据由工具查找 CAS、校验并复制出来；返回路径保留原文件名和伴随文件结构。
普通副本可以被外部程序打开。缓存复用前检查其内容身份；修改副本不修改 CAS，
也不自动保存回原 run。

### 修改同一个 run

名称、标签、文字解释、报告和附件可在原 run 中更新：

```bash
cherries run tag add <run-id> weekly
cherries report edit <run-id> README.md
cherries file add <run-id> existing-plot.png --as figs/comparison.png
```

CLI/API 只暂存变化文件，并留下足够的事务恢复信息。
普通编辑更新当前版本；第一版不自动保留整份 run 的历史修订。
原执行参数、状态、代码与已消费输入绑定固定；报告修改更新 `updated_at`。

手工编辑文件后执行校验与索引刷新。接口发现来源绑定与 input pointer 不一致时
报错，不能静默将原执行改写成消费了新输入。

### 新的可视化

重跑渲染脚本或生成新的分析结果时，创建新的 run：

```bash
cherries run new --name smile-front --kind visualization
cherries file add <view-id> --from-run <simulation-id> \
  --path outputs/result.vtu --as inputs/result.vtu
cherries run exec <view-id> -- uv run python src/render.py
```

该 run 保存输入摘要、渲染代码 commit、参数和图片。
相机或 ParaView 设置作为配置/附件保存。若报告使用图片，则另复制实际文件到 assets。
调整已有图片的说明文字属于报告编辑；重新执行渲染属于新的可视化 run。

## 7. 导出、归档和本地清理

### 三种复制的范围

| 操作 | 包含内容 | 适用场景 |
| --- | --- | --- |
| 普通复制 run 文件夹 | 元数据、pointers、日志、指标、随附报告和素材 | 分享报告或查看元数据 |
| `run export --with-data` | 当前 run 的真实数据、报告及文件目录 | 交给其他软件或他人使用 |
| `run copy --to-store` | 选定 run、来源 run、CAS、归档 Git 与 LFS 闭包 | 迁移、归档、独立恢复 |

普通目录副本里的 pointer 仍需要 CAS。`export --with-data` 也不等于完整源码与依赖归档。
跨 Store 复制才检查完整恢复所需的来源及代码闭包。

### 从本机归档到 NAS

```bash
cherries run copy <run-id> --to-store /mnt/DATA41-Users2/liqin/cherries
```

执行过程为：

1. 固定选择集，展开必须保留的来源 run 和代码依赖。
2. 检查目标已有对象和同 UUID 的记录，预先报告身份或编辑冲突。
3. 复制并校验缺少的 CAS 实体、Git 对象与 LFS 实体。
4. 复制 run 的控制文件和内联内容，最后发布目标正式 run 目录。
5. 核验目标所需引用闭包，返回逐 run 的复制结果与验证凭据。

源数据保留；相同内容重试可以跳过已完成项。目标已有记录的内容不同就报冲突，
不会依据文件时间覆盖。显式替换只允许可变内容差异，并核对预期目标 fingerprint。
同 UUID 的执行证据不同不能替换。

由于一个复制批次可能包含多个 run，单个 run 的目录改名只是它自己的发布边界。
run 要在所需来源记录已发布、完整闭包通过校验后才能标为可用；
批次中断时记录已完成项，重试补齐其余部分，不把半个批次说成全部完成。

### 归档后释放本地空间

```bash
cherries run delete <run-id> --dry-run
cherries run delete <run-id>
cherries store gc --dry-run
cherries store gc
```

先确认目标验证凭据，再查看本地删除计划。
本地仍保留的子 run 依赖该 run 时，删除被阻止；可把需要删除的完整选择集一起归档，
再一起删除。NAS 上有副本不会自动撤销本地依赖。

删除 run 会移除其正式目录和应用拥有的 run ref，保留最小删除凭据。
日志、指标、报告及 assets 的实际文件随目录清理释放；
CAS 仅在后续 GC 中删除全 Store 无引用的对象。

仍被其他项目或 run 引用的对象继续保留。Git/LFS 不由全局 CAS GC 删除，
按归档仓库自己的保留 refs 和可达闭包单独维护。
因此空间报告需要列出实际删除的目录字节、回收的独占 CAS 字节和仍被共享的字节。

## 8. 索引、恢复与完整性检查

权威记录来自项目/run 文件、pointers、实际内联内容和 Git refs。
SQLite 放在查询机器本机，缓存筛选字段和来源关系，不放在 NAS 上供多机共同写入。

正常修改增量更新索引。手工改动后 `index refresh`；缓存损坏或换机器时
`index rebuild`。重建只读控制信息和摘要，不对所有大文件重新哈希。
完整字节校验另由 `store verify --objects` 执行。

`store recover` 处理 `.tmp`、未完成编辑/复制/删除事务；没有明确证据时保留现场。
保存确认、临时清理、索引更新分别返回结果。
已经保存但缓存更新失败的 run 仍是有效记录；已发布但持久性未确认则显式报告。

GC 直接扫描所有项目的权威引用，并保护未发布工作、事务和已登记的保全材料。
存在活动运行、未核对的临时目录、损坏 pointer 或未知迁移材料时先停止回收。
不会根据陈旧索引或一次目录容量统计推断对象可删。

## 9. 最小日常工作流

```text
编辑 Git 工作区的代码与配置
→ 创建 UUID run
→ 固定输入，使用真实工作文件执行
→ 逐次记录 JSONL 指标与日志
→ 保存代码快照、Parquet、CAS 和 pointers
→ 发布正式 run
→ 查看结果，追加报告与标签
→ 创建新的分析/可视化 run
→ 将选定 run 与来源闭包复制到归档 Store
→ 验证目标
→ 删除不再需要的本地 run
→ 回收全 Store 无引用 CAS
```

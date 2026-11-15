# Cherries 存储设计

Cherries API，配套 [Python API](api.pyi)、[CLI](cli.md) 和 [样例](example.py)。

## 实验仓库

```text
<git-root>/                         # project-id 默认取此文件夹名
├── .git/                          # 日常开发历史
├── .gitignore                     # 忽略 cherries/ 及各 study 的 data/、figs/、tmp/
├── README.md
├── pyproject.toml / uv.lock
├── submodules/                    # Apple、Melon 等库子模块
├── exp/YYYY/mm/dd/<study>/
│   ├── README.md                  # 研究问题、方法、结果汇总和 run 链接
│   ├── src/10-run.py              # 实验程序
│   ├── src/20-analyze.py          # 分析、可视化程序
│   ├── data/                      # input/output 的工作文件，运行前准备输入
│   ├── figs/                      # fig 的工作文件
│   └── tmp/                       # 调试中间文件，永不收集到 run
└── cherries/                      # 本地记录，不进工作仓库 Git
```

study 是可继续编辑的工作区；`cherries/runs/` 保存每次执行的独立记录。
study/README.md 汇总研究，run/README.md 解释该次结果；逐 run 报告只维护后者，
不再镜像到 docs/runs。源码和 study README 进 Git；data/、figs/、tmp/、cherries/ 被忽略。

## 本地与远端

```text
<git-root>/.git/
├── objects/                      # 开发提交与 run 快照共享 Git 对象
├── refs/cherries/runs/<UUIDv7>     # 每个 run 的结束快照
├── modules/                      # 子模块的 Git/LFS 仓库
└── lfs/objects/                  # 源码仓库使用的 LFS 对象
<git-root>/cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/

<remote>/                         # CLI push/pull 指定的挂载目录
├── objects/sha256/ab/cd/<digest>
└── projects/<project-id>/
    ├── <project-id>.git/          # 同一快照及完整 Git/LFS 内容
    └── runs/YYYY/mm/dd/<UUIDv7>[.tmp]/
```

本地无应用层 CAS，真实文件优先 reflink，不支持或跨文件系统时普通复制。
不使用 symlink/hardlink。
入口脚本取 `__main__.__file__`，位置为 `<study>/src/<script>.py`；study 是 src 的
父目录，repo 是包含 study 的 Git 根。project-id 默认 Git 根文件夹名。
UUIDv7 是 run 标识并用于按创建时间排序；CLI 接受完整 ID 或具体 run 路径。
日期严格取 run.yaml 已持久化 start-time 的原始本地日期，不从 UUID、study 路径、
end-time 或当前时间推断。运行中使用 `.tmp`，结束后在同一日期分区改为正式目录。
例如 start-time 为 `2026-11-15 23:59:00+08:00`，即使次日结束或在其他时区
push/pull，仍使用 `runs/2026/11/15/<UUIDv7>/`。仅支持此按日布局，不兼容历史平铺格式。
日期目录按需创建；remove 删除记录后向上清理空的日、月、年及 runs 目录，
在本地 cherries 根或远端 project 根之前停止。
不保留空日期目录，也不增加远端索引。CAS、Git ref 和原生源码仓库路径不含日期。

本地合用标准 `.git`，不再建第二个 bare 仓库；HEAD、分支和用户暂存区保持原状。
`refs/cherries/runs/*` 按 [Git 原生规则](https://git-scm.com/docs/git-gc#_notes)保留快照对象；
push/pull 显式传输该 ref 及源码所需的 Git/LFS 内容。

两端 run 的文件集合如下，目录按需创建：

| 内容 | 本地 | 远端 | 结束后 |
| --- | --- | --- | --- |
| `run.yaml` | 下述 YAML | 同左 | 名称、description、tags、metadata 可编辑 |
| `run.log` | UTF-8 stdout/stderr、生命周期和异常 | 原样复制 | 固定 |
| `metrics.parquet` | 可选，四列 | 原样复制 | 固定 |
| `inputs/`、`outputs/` | 真实文件 | 无物理目录，YAML 引用 CAS | 固定 |
| `src/` | 仅入口脚本，保留原文件名，如 `10-run.py` | 原样复制 | 固定 |
| `figs/` | 真实文件 | 无物理目录，YAML 引用 CAS | 可追加/编辑 |
| `assets/`、`reports/`、`README.md/html` | 真实文件 | 原样复制 | 可追加/编辑 |

产物清单直接放在 run.yaml.artifacts，不增加 sidecar、状态、索引、版本或引用计数文件。
Git/LFS 使用原生格式。目录登记展开为文件，保留相对层级；空目录省略，不创建占位文件。
本地记录、add、pull 和 get 只为实际文件创建父目录。远端不创建 inputs/、outputs/、figs/。

## 特殊文件

`run.yaml` 使用 UTF-8、安全 YAML、两空格缩进，包含以下字段；description 为唯一可选字段：

```yaml
project-id: phace-exp
run-id: 01a1d75a-947b-7abc-8def-0123456789ab
run-name: 10-run
description: 检查网格读写前后的点数和单元数。
start-time: "2026-11-15 08:00:00+08:00"
end-time: "2026-11-15 08:03:12+08:00"
tags: []
params:
  mesh: /work/phace-exp/exp/2026/11/15/example/data/mesh.vtu
  result: /work/phace-exp/exp/2026/11/15/example/data/result.vtu
commit: "0123456789abcdef0123456789abcdef01234567"
metadata: {}
artifacts:
  inputs:
    - name: mesh.vtu
      sha256: ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
      size: 3
  outputs: []
  figs: []
```

artifacts 为必需字段，包含 inputs、outputs、figs 三个列表，空角色使用 `[]`。
每个条目恰含 name、sha256、size：name 是相对 study/data（inputs/outputs）或
study/figs（figs）的 POSIX 路径，使用 `/`，不可绝对或越出根目录；同一角色内 name 唯一。
sha256 为完整小写 SHA-256，size 为非负字节数。目录只展开实际文件，不登记目录条目。
本地收集时先保存文件，再计算已保存副本的 digest/size；两端使用同一清单。
inputs/outputs 清单结束后固定；artifacts 中仅 figs 可通过 add 或同步更新。

实验参数全部在脚本中定义；BaseConfig 是普通的
[Pydantic BaseModel](https://docs.pydantic.dev/latest/concepts/models/)。
`run(main)` 根据 main 的参数类型构造 `Config()`，以 `model_dump(mode="json")`
记录 params，Path 直接存绝对路径字符串；main 接收同一个配置实例。main 无参数时
params 为 `{}`。脚本及其中的参数定义随结束源码快照保存。
start-time/end-time 分别使用记录时机器的本地时区，包含显式数字偏移，
格式为 `YYYY-mm-dd HH:MM:SS±HH:MM`，精确到秒。
start() 记录 start-time；main 返回或手动调用 end() 时记录 end-time，随后收集产物。
运行中 end-time 为 null；两个时间结束后固定，push/pull 原样保留字符串，
目的端时区不同也不转换。
description 是 user/AI 指定的简短说明，可根据结果修改；未指定时省略该键。
metadata 少量使用。录制中 commit 为 null；封存后为
本地及远端 `refs/cherries/runs/<run-id>` 的原生 Git OID（40 或 64 位）。ref 只创建一次；
loose ref 内容为 OID 加 LF，读取通过 Git，兼容 packed-refs。身份、params、时间和 commit 固定。

运行中用 `metrics.jsonl`，结束转换为 Parquet 后删除 JSONL。
无指标则两者均可省略。只有四列：`key: String`、`value: Float64`、`step: Int64`、
`timestamp_ms: Int64`（Unix 毫秒）。

```jsonl
{"key":"points","value":42.0,"step":0,"timestamp_ms":1794614400123}
```

step 初始 0，仅 set_step 修改；None 使用当前 step/时间。同批共用 step/时间，
保留追加顺序和重复行。每次指标调用追加后 flush，批量共用一次 flush。
NaN/±Inf 在 JSONL 用字符串 `"NaN"`、`"Infinity"`、`"-Infinity"`，Parquet 恢复浮点。

远端 CAS digest 是完整小写 SHA-256，包含目录前缀 abcd；同 digest 一个对象。
对象名无后缀，保存真实文件字节；按内容哈希入库，相同内容复用对象。
例如 `outputs/mesh.vtu` 由 artifacts.outputs 中 name 为 mesh.vtu 的条目定位 CAS。
零字节文件仍有 size: 0、空内容 SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`，
远端保存真实的零字节 CAS 对象。应用层不使用 `.lfs` pointer；`.lfs` 可是普通数据文件名。
源码的 Git LFS 在本地使用 `.git/lfs/objects/`，远端使用
`<project-id>.git/lfs/objects/`，与 CAS 分开，原生格式不变。

run.yaml 是产物元数据的权威来源；files/get/pull 根据清单解析逻辑路径。
verify 显式读取已保存文件或 CAS 对象，校验记录的大小和 SHA-256。
GC 通过扫描所有 run.yaml.artifacts 获取 CAS 引用，无需读取大型对象内容。
远端写入与 GC 由同一客户端管理；同路径 Store 的提交和 GC 用本机缓存中的进程锁互斥，
锁文件不进入远端。
派生内容 lineage 与 prune 仍是提案；清单可支持只扫描 YAML 的依赖分析。

## API 与流程

- input/output 的相对路径以 study/data 为根，fig 以 study/figs 为根，均立即返回
  绝对工作路径；绝对路径也必须在对应 study/data 或 study/figs 内，外部文件先准备到该根目录。
  input("mesh.vtu") 返回
  `<git-root>/exp/YYYY/mm/dd/<study>/data/mesh.vtu`，fig("loss.png") 返回同 study 的
  `figs/loss.png`。output/fig 创建父目录。
- input/output/fig 始终解析路径并登记文件，Config 与 main 中调用完全相同。
  登记集合从脚本加载时开始收集，start 保留已有登记，main 的调用继续加入同一集合。
- `tmp("debug/intermediate.vtu")` 返回 study/tmp 下的绝对路径并创建父目录，
  绝对路径和相对路径都不能越出该根目录。tmp 从不登记或收集，无论是否调试。
- `cherries.run(main)` 自动开始、构造配置并记录 params、调用 main、结束。
  end 按工作目录内的相对层级，将已登记输入、输出和图的结束时内容复制到
  run/inputs、run/outputs、run/figs；使用 reflink 或普通复制，再计算保存副本的 hash/size
  并写入 artifacts。
- 结束时转换 metrics、采集一次 Git 快照、保存入口脚本到 src/、写 commit/ref，最后将 `.tmp`
  改名。此后的工作区变化不改动已保存的输入、输出和源码副本。

调试使用 `DEBUG=1 python src/10-run.py`。仅 start 时环境变量恰为 `1` 启用；
本次执行保持该模式。run 正常构造 Config、调用 main 一次，返回 None；普通录制
返回已保存目录的 Path。调试不序列化配置，不创建 run 目录、日志、指标、YAML、
产物副本或 Git 快照，也不查询 Git，因此同样的 study/src 布局可在 Git 仓库外调试。
input/output/fig/tmp 保持原工作区路径及父目录创建规则，输出留在工作区。
log_metric/log_metrics 不记录，get_step/set_step 仍工作且初始为 0。
stdout/stderr 保留在终端，原异常照常抛出。手动 start/end 同样支持；end 仅清理
调试执行状态，不收集文件。调试不增加任何持久化字段。

## Git snapshot

仅在 end() 时采集一次结束状态，使用 Git plumbing：

1. 记下当前 HEAD，读取真实索引中的 tracked 路径；每个仓库以独立、未占用的
   临时路径设置 `GIT_INDEX_FILE`，用 `git read-tree HEAD` 初始化，无 HEAD 时用 `--empty`。
2. 用 `git update-index --force-remove` 从临时索引移除 cherries/ 及各 study 的
   data/figs/tmp，再按相同排除规则执行 `git add -A`，采集修改、删除及未忽略的 untracked
   文件。真实索引中新暂存的 ignored 源文件单独加入；已 tracked 的排除项也移除。
3. 先递归采集子模块，再以 `git update-index --cacheinfo` 写入子快照 gitlink。
   子模块使用自己的临时索引和同名 run ref，父索引环境不传给子模块。
4. `git write-tree` 生成树，`git commit-tree <tree> -p <HEAD>` 生成提交；无 HEAD
   时不传父节点。父节点始终是源码 HEAD，不串联 run；无改动可复用 HEAD。
5. Git add 使用仓库的 LFS clean filter 保存 pointer 与实际 payload。
   通过 `git update-ref --stdin` 的 `create refs/cherries/runs/<id> <commit>`
   创建引用，写入 run.yaml.commit，从该提交提取入口脚本至 `src/<script>.py`。

临时索引清理后，用户 HEAD、分支、暂存区和工作文件保持原状。
[临时索引](https://git-scm.com/docs/git#Documentation/git.txt-GITINDEXFILE)、
[commit-tree](https://git-scm.com/docs/git-commit-tree)、[create-only ref](https://git-scm.com/docs/git-update-ref)。
远端保留所需父历史及独立子仓库的 Git/LFS 对象，含历史 gitlink 指向的子提交；
gitlink 本身不包含子仓库字节。完整项目状态由 Git ref 保存，run 的 src/ 只存入口脚本。

## README 与 reports

AI 开始或恢复研究时先读相关 README/reports；获得重要结果、形成决定或发现错误后，
主动更新研究问题、方法、证据、解释与结论，并注明更正依据。study/README.md 汇总
研究并链接 run；每个 run 的 README/reports 维护该次结果与后续分析。
默认使用 Markdown；复杂布局或交互式可视化使用 HTML。run 只有一份报告时，
直接保存为 run 根目录的 README.md 或 README.html，不放入 reports/。只有多份报告时，
才将附加报告保存到 reports/；README 可以充当入口并链接详细报告，避免重复维护正文。

结束后 inputs/outputs/src/ref、params、start-time/end-time、日志和指标固定。user/AI 可在同一 run 分析、
撰写报告，不刷新原 ref。事后分析在 study 的 figs/ 写图，再用 CLI add 保存到选定
run 的 figs/，需直接展示的图另存真实 assets 副本。README 引用 `assets/图名`，
reports/ 直属报告引用 `../assets/图名`，更深层报告按所在位置调整相对路径。
这样更换 study 的图不会覆盖其他 run 的图。

CLI push 将本地输入/输出/图写入远端 CAS，通过 run.yaml.artifacts 定位；
pull 根据清单物化为真实文件。
两者复制同一 ref 及所需 Git/LFS 对象。首次传输在原始 start-time 对应的
`YYYY/mm/dd/<id>.tmp/` 准备，完成后同分区 rename；
后续同步可变资料和名称/description/tags/metadata，素材先于报告。push 保留远端
独有资料，pull 保留本地独有资料；figs 按 name 合并，保留目的端独有图，
同名图遵循同步覆盖规则。先保存 payload，再原子发布 run.yaml，避免清单引用未就绪对象。
执行内容、artifacts.inputs/outputs 及原 Git snapshot 固定。

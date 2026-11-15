# Cherries CLI

与 [Python API](api.pyi)、[存储设计](storage.md) 配套的管理接口。

## 位置与输出

```text
cherries [--repo REPO] [--project-id ID] [--remote ROOT] COMMAND ...
```

共有选项放在 COMMAND 前。默认操作本地 `<git-root>/cherries/`；repo 为已有 Git
工作仓库，默认从 cwd 发现。project-id 默认 Git 根文件夹名；
仓库外操作远端须显式指定 ID。
remote 是挂载的存储根目录；push 将其作为目的端，pull 作为来源端。
目录首次写入时创建，不增加配置、索引或状态文件。

RUN 使用完整 UUID 或具体 run 目录路径。UUID 是标识，查询时扫描日期分区定位正式目录；
`.tmp` 使用目录路径，表示尚未封存。edit/add/push/pull 操作已完成的记录。
本地路径为 `<git-root>/cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`，远端为
`ROOT/projects/<project-id>/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`。日期严格取
run.yaml 已持久化 start-time 的原始本地日期，不从 UUID、study 路径或当前时间推断。
仅支持此按日布局，不兼容历史平铺格式；不另建远端索引。
PATH/TARGET 是 run 内相对路径；SOURCE/DEST 相对 cwd 解析。
创建或复制文件的命令成功后输出绝对路径；进度、日志与诊断写 stderr。
退出码为 0 表示成功，非零表示操作失败。

## 实验启动

```bash
# 在 study 目录运行；先准备 data/mesh.vtu
python src/10-run.py
# 调试执行，不生成记录
DEBUG=1 python src/10-run.py
```

脚本末尾调用 `cherries.run(main)`。main(cfg: Config) 的配置由 run 自动构造；
实验参数在脚本中定义，run.yaml.params 普通序列化配置，Path 为绝对路径。
CLI 用于已有记录的查询、编辑和同步。

仅启动时环境变量恰为 `DEBUG=1` 启用调试模式；执行中改环境变量不会切换模式。
仍构造 Config 并调用 main 一次，路径辅助函数保持工作区路径，指标调用不记录，
step 从 0 开始且可读写。stdout/stderr 保留在终端，异常照常抛出。
不生成 run 目录、日志、指标、metadata、产物副本或 Git 快照，也不序列化配置；
`run(main)` 返回 None，正常记录返回 Path。手动 start/end 同样支持，调试不要求 Git。
`cherries.tmp("debug/intermediate.vtu")` 返回 study/tmp 下的绝对路径并创建父目录，
无论是否调试都不收集；Git 快照也排除 study 的 data/figs/tmp，包括已 tracked 文件。

## 查询

```text
cherries list [--tag TAG]... [--param KEY=JSON]... [--search TEXT]
  [--limit N] [--unfinished] [--json]
cherries show RUN [--json]
cherries files RUN [PATH] [--json]
cherries get RUN PATH --output DEST [--overwrite]
```

list 扫描各 `YYYY/mm/dd/` 分区中的 run.yaml，默认列出已封存记录，按 UUIDv7 倒序，limit 默认 20。
`--unfinished` 仅列 `.tmp`；所有筛选条件取 AND，search 对名称/description 作子串匹配，param
对顶层参数作 JSON 值相等比较。show 输出 run.yaml。JSON 模式：list 为 YAML 对象
数组，show 为单个对象，files 为逻辑路径数组；不增加记录字段。

files/get 使用 run 内逻辑路径，如 `outputs/result.vtu`；产物路径由
run.yaml.artifacts 解析，远端从 CAS 读取，实际文件名可含 `.lfs` 后缀。
PATH 可为文件或目录，files 默认根目录。get 复制/物化真实文件到 DEST；
DEST 是文件或目录本身的目标路径。overwrite 用于替换同名文件，目录中其他文件保留。

## 修改说明与汇报

```text
cherries edit RUN [--name TEXT] [--description TEXT | --clear-description]
  [--add-tag TAG]... [--remove-tag TAG]...
  [--metadata KEY=JSON]... [--unset-metadata KEY]...
cherries add RUN SOURCE --as TARGET
```

edit 修改名称、description、tags、metadata；clear-description 删除该可选键。
tag 按集合增删。add 复制文件/目录到指定可变路径，同名替换、其他文件保留；TARGET 指向
figs/、assets/、reports/ 内路径，或 README.md、README.html。本地保存真实文件；
figs 更新清单中对应 name 的 hash/size；远端只保存 CAS 对象，其余可变资料直接保存。
as 给出完整目标路径；目录展开为文件，空目录省略。payload 先保存，再原子发布 YAML。
edit 返回 run 目录，add 返回逻辑目标路径；远端 figs 没有对应物理目录。

AI 主动维护研究及 run 的 README/reports，按结果更新 description；默认 Markdown，
复杂布局或交互式可视化采用 HTML。run 只有一份报告时，将其保存为根目录的
README.md 或 README.html；只有多份报告时，才用 reports/ 保存附加报告。README
可以充当入口并链接详细报告，避免重复维护正文。素材先保存到 assets，再更新引用它的报告；
根 README 引用 `assets/图名`，reports/ 直属报告引用 `../assets/图名`，
更深层报告按所在位置调整相对路径。

```bash
cherries edit "$RUN" --description '网格读写前后点数与单元数一致' --add-tag checked
cherries add "$RUN" figs/mesh.png --as figs/mesh.png
cherries add "$RUN" figs/mesh.png --as assets/mesh.png
cherries add "$RUN" analysis.md --as README.md
cherries add "$RUN" interactive.html --as reports/interactive.html
```

上例先保存 README.md，再添加第二份交互式报告；若只有交互式报告，将其保存为 README.html。

## 上传与取回

```text
cherries --remote ROOT push RUN
cherries --remote ROOT pull RUN [--overwrite]
```

push 从本地读取；pull 从远端读取并保存到所选 repo 的 cherries/runs/YYYY/mm/dd。
两者复制同一 commit/ref 及所需 Git/LFS 对象；pull 根据 artifacts 清单从 CAS
物化真实文件，并导入 refs，不 checkout 或改动工作区代码。

首次传输在原始 start-time 对应的 `YYYY/mm/dd/<id>.tmp/` 准备，完成后同分区 rename。
重复 push 更新可变资料并保留远端
独有文件；pull 保留本地独有文件，overwrite 用于替换已有可变资料。
figs 按 name 合并并保留目的端独有图，inputs/outputs 清单保持固定。
先保存 payload，再原子发布 YAML；远端无 inputs/outputs/figs 物理目录。
执行内容沿用原记录，start-time/end-time 保留原始本地时间和偏移字符串，
目的端时区不同也不转换，日期分区也保持不变；跨日结束同样不换分区。
成功后输出目标 run 目录；push 保留本地记录。

## 删除、回收与校验

```text
cherries remove RUN
cherries gc [--dry-run]
cherries verify RUN
```

remove 删除选定副本的 run 目录及主仓库/子模块中对应的 run refs；保留工作区
data/figs、其他副本与共享对象。未封存记录使用 `.tmp` 路径选择。
删除后向上清理空的日、月、年及 runs 目录，保留本地 cherries 根、远端 project 根
及仍有记录的日期目录。

gc 针对整个选定存储，project-id 不缩小其范围；默认实际回收，dry-run 只列计划与
字节数。扫描存储中的引用后回收：
远端 CAS 扫描所有 project（含 `.tmp`）的 run.yaml.artifacts 引用，无需读取大型 CAS
对象内容；Git/LFS 保留其他 refs、
reflog 及历史 gitlink 所需的对象闭包。本地无 CAS；回收结果输出对象数和字节数。

verify 只读检查 schema、文件集合、清单记录的 hash/size、commit/ref、子模块及
LFS 内容完整性；读取实际文件或 CAS 字节核对产物元数据。输入、输出、src、params、start-time/end-time、日志、指标与 Git ref 在结束后固定。

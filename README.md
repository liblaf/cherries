<div align="center" markdown>
<a name="readme-top"></a>

![Cherries](https://socialify.git.ci/liblaf/cherries/image?description=1&forks=1&issues=1&language=1&logo=https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Ffluentui-emoji%2Frefs%2Fheads%2Fmain%2Fassets%2FCherries%2F3D%2Fcherries_3d.png&name=1&owner=1&pattern=Transparent&pulls=1&stargazers=1&theme=Auto)

**[Explore the docs »](https://liblaf.github.io/cherries/)**

[![Test](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml/badge.svg)](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml)
[![PyPI - Version](https://img.shields.io/pypi/v/liblaf-cherries?logo=PyPI&label=PyPI)](https://pypi.org/project/liblaf-cherries)
[![Python](https://img.shields.io/pypi/pyversions/liblaf-cherries?logo=Python)](https://pypi.org/project/liblaf-cherries)

</div>

---

## Experiment stores

Cherries records computations and visualizations as editable run folders. All
projects in a store share SHA-256 file contents; ordinary YAML, reports, logs and
Parquet metrics remain directly readable. Each execution retains a real Git end
ref and an independent source archive, including submodules and Git LFS data.

Linux and Python 3.12 or newer are supported. Git is required; source histories
containing LFS files also require Git LFS.

```bash
uv add liblaf-cherries
cherries store init /data/cherries
cherries --store /data/cherries project add my-project --repo .
```

Select the project and storage at the source repository root:

```toml
# cherries.toml
[project]
id = "my-project"

[recording]
on_error = "keep"
metric_durability = "fsync"
```

```toml
# cherries.local.toml, normally Git ignored
[store]
path = "/data/cherries"
```

`--store` overrides `CHERRIES_STORE` and configured paths. `--project` overrides
`CHERRIES_PROJECT` and `[project].id`. Opening a store never initializes or
cleans it implicitly.

## Record an experiment

```python
from liblaf import cherries

with cherries.run(name="baseline", parameters={"steps": 200}) as run:
    result = run.output("answer.txt")
    result.write_text("42\n")
    run.log_metric("loss", 0.001, step=200)
    run.report("README.md").write_text("# Baseline\n\nAnswer: 42.\n")

print(run.result.run_id)
```

Execute normally with `uv run python experiment.py`, or use the CLI to record
an external command and its native output:

```bash
cherries run exec --name baseline -- uv run python experiment.py
```

A CLI controller and an inner Python context share one run. During execution,
`CHERRIES_RUN_DIR` identifies the ordinary work directory. `input()` fixes content
before returning a readable copy; `output()` and `figure()` declare required
files; `scratch()` provides unretained working paths. Complete all asynchronous
writes before returning from the context.

Metrics append to JSONL with explicit durability, then convert to Parquet when
saved. Duplicate steps and timestamps are retained. Execution failures keep
marked diagnostic runs by default; recording failures preserve unpublished work.

## Read, explain and visualize

```bash
cherries run list --status succeeded --where 'metrics["loss"].last < 0.01'
cherries run show <run-id>
cherries file get <run-id> outputs/answer.txt --to ./answer.txt
cherries run tag add <run-id> selected
cherries report edit <run-id> README.md
```

Reports, assets, names and tags can change after execution. Original execution
parameters, results, source commits and consumed inputs stay fixed. A new
calculation or visualization creates a new run and binds exact input contents:

```python
store = cherries.Store.open("/data/cherries")
project = store.projects.get("my-project")
saved = project.runs.get("<run-id>")
source = saved.file("outputs/answer.txt").ref()

with project.run(name="comparison", kind="analysis") as analysis:
    answer = analysis.input(source, name="answer.txt")
    analysis.output("comparison.txt").write_text(answer.read_text())
```

## Archive and reclaim space

```bash
cherries run copy <run-id> --to-store /archive/cherries
cherries code checkout <run-id> --to ./source-copy
cherries project verify my-project --git --lfs --offline
cherries run delete <run-id> --dry-run
cherries store gc --dry-run
```

Initialize the destination store before copying. Copy includes source runs, CAS
and source Git/LFS closure and checks conflicts before publication. Deletion
checks retained dependents. Global GC reads authoritative references across every
project. Remove `--dry-run` to apply the reviewed deletion or GC operation.

## Storage and compatibility

```text
store/
  store.yaml
  objects/sha256/ab/cd/<full-digest>.<suffix>
  projects/<project>/
    project.yaml
    <project>.git/
    runs/<uuid>.tmp/             # unpublished work
    runs/<uuid>/
      run.yaml  run.log  metrics.parquet
      inputs/...lfs  outputs/...lfs  figs/...lfs
      README.md  reports/...  assets/...
```

The CAS contains real file bytes. Standard pointer files reference digest and
size; suffix changes do not invalidate them. Reports carry ordinary asset copies.
Each bare repository has its own self-contained LFS store, which can duplicate
bytes also retained by CAS. SQLite indexes and materialized file copies live in
machine-local caches and can be rebuilt.

The v4 immutable collection format remains available through
`liblaf.cherries.legacy` and `cherries legacy ...`. Existing explicit v4
configuration uses its old recorder; new stores are never opened as collections.
Explicit imports preserve original IDs and evidence limitations:

```bash
cherries run import /old/collection --inspect
cherries run import /old/collection
```

Legacy source evidence is retained as audit attachments; importing bytes does
not establish executable source recovery or verified replay.

Read the [workflow and CLI documentation](https://github.com/liblaf/cherries/blob/main/docs/README.md),
[detailed storage workflow](https://github.com/liblaf/cherries/blob/main/docs/design/storage-workflow.md)
and [API design](https://github.com/liblaf/cherries/blob/main/docs/design/storage-cli-api.md).

## Development

```bash
uv sync
uv run pytest
uv run nox
uv run ruff check .
uv run lint-imports
uv build
```

## License

Copyright © 2026 [liblaf](https://github.com/liblaf).
[MIT](https://github.com/liblaf/cherries/blob/main/LICENSE).

<div align="center" markdown>
<a name="readme-top"></a>

![Cherries](https://socialify.git.ci/liblaf/cherries/image?description=1&forks=1&issues=1&language=1&logo=https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Ffluentui-emoji%2Frefs%2Fheads%2Fmain%2Fassets%2FCherries%2F3D%2Fcherries_3d.png&name=1&owner=1&pattern=Transparent&pulls=1&stargazers=1&theme=Auto)

**[Explore the docs »](https://liblaf.github.io/cherries/)**

[![Test](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml/badge.svg)](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml)
[![PyPI - Version](https://img.shields.io/pypi/v/liblaf-cherries?logo=PyPI&label=PyPI)](https://pypi.org/project/liblaf-cherries)
[![Python](https://img.shields.io/pypi/pyversions/liblaf-cherries?logo=Python)](https://pypi.org/project/liblaf-cherries)

</div>

---

## Experiments as files

Cherries records Python experiments in ordinary local folders: end-of-run
`inputs/`/`outputs/`/`figs/` copies (using Linux reflinks when available), the
entry script plus `src/diff.patch` against `HEAD`, logs and Parquet metrics.
Remote archiving delegates deduplication, locking, verification and GC to
[Restic](https://restic.net/), storing one tagged snapshot per run.

Requires Linux, Python 3.12+ and Git. Remote commands (`--remote`) require
[Restic](https://restic.net/) 0.17+.

```bash
uv add liblaf-cherries
```

## Run a script

```text
project/
  .git/
  exp/2026/11/15/example/
    README.md
    src/10-run.py
    data/                    # inputs and outputs
    figs/                    # figures
    tmp/                     # debug intermediates; never saved
  cherries/runs/YYYY/mm/dd/  # saved local runs, partitioned by start date
```

Ignore `cherries/` and each study's `data/`, `figs/` and `tmp/` in Git:

```python
from pathlib import Path

from liblaf import cherries


class Config(cherries.BaseConfig):
    factor: int = 2
    source: Path = cherries.input("input.txt")
    result: Path = cherries.output("result.txt")


def main(cfg: Config) -> None:
    value = int(cfg.source.read_text()) * cfg.factor
    cfg.result.write_text(str(value))
    cherries.tmp("debug/value.txt").write_text(str(value))
    cherries.log_metric("answer", value)


if __name__ == "__main__":
    cherries.run(main)
```

Run normally with `python src/10-run.py` (returns saved run `Path`), or debug
without recording via `DEBUG=1 python src/10-run.py` (returns `None`, keeps
stdout/stderr in the terminal, works outside Git). Dirty Git LFS files and dirty
Git submodules are rejected before and after execution; committed LFS files and
clean submodules are allowed.

## Manage, prune and archive

```bash
cherries list --tag selected --json
cherries show RUN
cherries path RUN
cherries edit RUN --description 'Result checked' --add-tag selected
cherries add RUN analysis.md --as README.md
cherries add RUN figs/loss.png --as figs/loss.png
cherries lineage --tag selected
cherries prune --tag selected --dry-run
cherries verify RUN
cherries remove RUN
cherries --remote /mnt/archive/cherries push RUN
cherries --remote /mnt/archive/cherries pull RUN
cherries --remote /mnt/archive/cherries list --tag selected --json
cherries --remote /mnt/archive/cherries lineage --tag selected
cherries --remote /mnt/archive/cherries prune --tag selected --dry-run
cherries --remote /mnt/archive/cherries gc --dry-run
```

Local runs are ordinary folders (`cherries path RUN` prints the path for direct
`ls`/`cp`). `lineage` and `prune` follow transitive SHA-256 dependencies from
`run.yaml.artifacts` (ignoring zero-byte files) on both local runs and Restic
archives. Remote snapshots are immutable: edit reports or figures locally with
`edit`/`add` and re-push.

See the [storage design](https://github.com/liblaf/cherries/blob/main/docs/design/cherries/storage.md)
and [CLI reference](https://github.com/liblaf/cherries/blob/main/docs/design/cherries/cli.md)
for exact formats and options.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run lint-imports
uv run zensical build
```

## License

Copyright © 2026 [liblaf](https://github.com/liblaf).
[MIT](https://github.com/liblaf/cherries/blob/main/LICENSE).

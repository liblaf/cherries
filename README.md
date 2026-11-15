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

Cherries records Python experiments in ordinary folders. A run keeps end-of-run
input/output copies, its entry script, a Git snapshot, logs and Parquet metrics.
Local copies use reflinks when available. Remote archives share SHA-256 contents
across projects and keep self-contained Git/LFS repositories.

Requires Linux, Python 3.12+ and Git. Source repositories using Git LFS also need
Git LFS installed.

```bash
uv add liblaf-cherries
```

## Run a script

Use an experiment repository with this layout:

```text
project/
  .git/
  submodules/
  exp/2026/11/15/example/
    README.md
    src/10-run.py
    data/                 # prepare input files here
    figs/
    tmp/                  # debug intermediates; never saved in runs
  cherries/runs/YYYY/mm/dd/  # saved local runs, partitioned by start date
```

Ignore `cherries/` and each study's `data/`, `figs/` and `tmp/` in Git. Put parameters in
the script. Save this example as `src/10-run.py`, prepare `data/input.txt`, then
execute `python src/10-run.py`:

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

`input()` and `output()` return absolute paths under the study's `data/`;
`fig()` uses its `figs/`. `tmp()` uses `tmp/`, creates parent directories and never
registers or collects its files. Calls in Config and main behave identically. Registered
files are copied at the end and recorded in `run.yaml.artifacts` with their
relative name, SHA-256 and byte size. Paths must stay under the corresponding
study `data/`, `figs/` or `tmp/` root; prepare outside files there before registering them. `run(main)` constructs the annotated config and
records its values, including absolute paths. Each run's `src/` holds just the
entry script; `refs/cherries/runs/<UUIDv7>` preserves the complete end snapshot.
The run records `start-time` and `end-time` in the machine's local timezone at
each instant, with an explicit numeric offset: `YYYY-mm-dd HH:MM:SS±HH:MM`
(for example, `2026-11-15 08:00:00+08:00`). `start()` captures the start; main
returning or manual `end()` captures the end before artifact copying and Git
finalization. While running, `end-time` is null.

For debugging, run `DEBUG=1 python src/10-run.py`. Cherries constructs the config
and calls main once, leaves stdout/stderr in the terminal and returns `None`.
It creates no run directory, logs, metrics, metadata, artifact copies or Git
snapshot, and does not serialize the config. Path helpers still use the study
workspace; outputs and intermediates remain there. Metric logging does nothing;
`get_step()` and `set_step()` still work, starting at zero. Exceptions propagate
without creating a record. Manual `start()`/`end()` supports the same behavior.
Only the exact value `DEBUG=1` enables this mode when execution starts; changing
the environment during execution does not switch it. Debugging also works
outside Git with the same `<study>/src/<script>.py` layout. Normal `run(main)`
returns the saved run directory (`Path`). Git snapshots exclude study `tmp/`
alongside `data/` and `figs/`, even when those files are already tracked.

## Inspect, explain and archive

```bash
cherries list --tag selected --json
cherries show RUN
cherries files RUN
cherries get RUN outputs/result.txt --output ./result.txt
cherries edit RUN --description 'Result checked' --add-tag selected
cherries add RUN analysis.md --as README.md
cherries add RUN figs/loss.png --as assets/loss.png
cherries --remote /mnt/archive/cherries push RUN
cherries --remote /mnt/archive/cherries pull RUN
cherries verify RUN
cherries remove RUN
cherries --remote /mnt/archive/cherries gc --dry-run
```

After execution, maintain the run's README, reports, assets and figures. Inputs,
outputs, source, parameters, start/end times, log, metrics and Git ref stay fixed.
Push and pull preserve the exact original strings across destination timezones.
Default to Markdown; use HTML for complex layouts or interactive figures. When a
run has one report, save it as `README.md` or `README.html` at the run root. Use
`reports/` only for additional reports when the run has multiple reports. The
README can serve as an entry point linking detailed reports without repeating
their text. Reference images as `assets/image.png` from the root README and
`../assets/image.png` from a report directly inside `reports/`; adjust relative
paths for deeper report folders.

Local runs use `cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`; remote runs use
`ROOT/projects/<project-id>/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`.
The date comes from the persisted `run.yaml` `start-time` in its original local
timezone. Finishing after midnight or pushing/pulling across timezones keeps that
partition. UUIDv7 remains the run identifier; CLI `RUN` accepts the ID or a concrete
run path. Running experiments use `.tmp`; completed records drop that suffix.
`list` defaults to completed records; `list --unfinished` selects `.tmp` records.
`remove` also removes empty date directories. Only this daily layout is supported.
Metrics append and flush to JSONL, then become four-column Parquet at the end.
Failures retain `.tmp` with diagnostic logs and re-raise the original exception.
The required `artifacts` mapping lists `inputs`, `outputs` and `figs`; empty roles
use `[]`. Local records keep real files alongside this manifest. Remote records
store these payloads only in extensionless CAS objects and resolve logical paths
such as `outputs/result.txt` through the manifest. Pull restores real files.
Repeat push updates editable materials and retains remote-only files and figures.
Repeat pull preserves existing local materials unless `--overwrite` is passed;
figures merge by name and destination-only figures remain. Payloads are saved
before the manifest is published atomically. `verify` checks recorded hashes and
sizes against the actual saved bytes.

The [storage specification](https://github.com/liblaf/cherries/blob/main/docs/design/cherries/storage.md),
[Python API](https://github.com/liblaf/cherries/blob/main/docs/design/cherries/api.pyi)
and [CLI reference](https://github.com/liblaf/cherries/blob/main/docs/design/cherries/cli.md)
describe the exact format and commands.

## Development

```bash
uv sync
uv run pytest
uv run nox
uv run ruff check .
uv run lint-imports
uv build
uv run zensical build
```

## License

Copyright © 2026 [liblaf](https://github.com/liblaf).
[MIT](https://github.com/liblaf/cherries/blob/main/LICENSE).

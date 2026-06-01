<div align="center" markdown>
<a name="readme-top"></a>

![Cherries](https://socialify.git.ci/liblaf/cherries/image?description=1&forks=1&issues=1&language=1&logo=https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Ffluentui-emoji%2Frefs%2Fheads%2Fmain%2Fassets%2FCherries%2F3D%2Fcherries_3d.png&name=1&owner=1&pattern=Transparent&pulls=1&stargazers=1&theme=Auto)

**[Explore the docs »](https://liblaf.github.io/cherries/)**

[![Test](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml/badge.svg)](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml)
[![codecov](https://codecov.io/gh/liblaf/cherries/graph/badge.svg)](https://codecov.io/gh/liblaf/cherries)
[![PyPI - Version](https://img.shields.io/pypi/v/liblaf-cherries?logo=PyPI&label=PyPI)](https://pypi.org/project/liblaf-cherries)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/liblaf-cherries?logo=Python&label=Python)](https://pypi.org/project/liblaf-cherries)
[![PyPI - Types](https://img.shields.io/pypi/types/liblaf-cherries?logo=PyPI&label=Types)](https://pypi.org/project/liblaf-cherries)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/liblaf/cherries/main.svg)](https://results.pre-commit.ci/latest/github/liblaf/cherries/main)

[Changelog](https://github.com/liblaf/cherries/blob/main/CHANGELOG.md) · [Report Bug](https://github.com/liblaf/cherries/issues) · [Request Feature](https://github.com/liblaf/cherries/issues)

![Rule](https://cdn.jsdelivr.net/gh/andreasbm/readme/assets/lines/rainbow.png)

</div>

## ✨ What Cherries Does

Cherries is a lightweight experiment runner for Python scripts that need just
enough structure to be repeatable. It builds typed config objects, resolves
stable data and temporary paths, stores scalar metrics as Polars dataframes, and
fans run events out to local files, Git, Comet, and custom plugins.

- **Typed configs**: pass `pydantic-settings` models into experiments and log
  them as parameters automatically.
- **Reproducible paths**: resolve inputs, outputs, and temporary artifacts below
  the entrypoint-derived run directory.
- **Metric history**: log one scalar or nested metric mappings such as
  `{"train": {"loss": 0.4}}`, then read them back as tables.
- **Artifact bundles**: log VTK `.series` frames and optional mesh
  `.landmarks.json` companions with their primary artifacts.
- **Plugin hooks**: compose ordered hooks for local snapshots, logging, Git,
  Comet, or your own integrations.
- **Run profiles**: use `debug` for local work without remote or commit side
  effects, and `default` for the full logging pipeline.

## 📦 Installation

```bash
uv add liblaf-cherries
```

## 🚀 Quick Start

```python
from pathlib import Path

from liblaf import cherries


class Config(cherries.BaseConfig):
    name: str = "world"
    output: Path = cherries.output("hello.txt", mkdir=True)


def experiment(cfg: Config) -> None:
    message = f"Hello, {cfg.name}!"
    cfg.output.write_text(f"{message}\n")
    cherries.log_params({"name": cfg.name})
    cherries.log_metric("message_length", len(message))


if __name__ == "__main__":
    cherries.main(experiment, profile="debug")
```

`profile="debug"` keeps Comet disabled and Git commits off while still copying
the entrypoint, logs, and logged artifacts into `.cherries/runs/`. The default
profile enables Comet, commits dirty changes when needed, and records the final
Git SHA.

## 🧭 Core Concepts

- `cherries.input()` logs existing inputs immediately.
- `cherries.output()` and `cherries.temp()` return paths immediately, then log
  existing files when the run ends.
- `cherries.log_metric()` records one scalar; `cherries.log_metrics()` flattens
  nested mappings with `/`.
- `CHERRIES_NAME` sets the human-readable run name; `CHERRIES_TAGS` attaches a
  comma-separated tag list to summaries and Comet.
- Plugins subclass `liblaf.cherries.core.Plugin`, decorate hooks with
  `liblaf.cherries.core.impl()`, and use `before` or `after` constraints for
  deterministic order.

## ⌨️ Local Development

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/liblaf/cherries)

```bash
gh repo clone liblaf/cherries
cd cherries
mise run install
uv run pytest
mise run lint
mise run docs:build
```

## 🔗 Links

- [Documentation](https://liblaf.github.io/cherries/)
- [Source Code](https://github.com/liblaf/cherries)
- [Issue Tracker](https://github.com/liblaf/cherries/issues)
- [PyPI Package](https://pypi.org/project/liblaf-cherries/)

---

#### 📝 License

Copyright © 2026 [liblaf](https://github.com/liblaf). <br />
This project is [MIT](https://github.com/liblaf/cherries/blob/main/LICENSE) licensed.

<div align="center" markdown>
<a name="readme-top"></a>

![Cherries](https://socialify.git.ci/liblaf/cherries/image?description=1&forks=1&issues=1&language=1&logo=https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Ffluentui-emoji%2Frefs%2Fheads%2Fmain%2Fassets%2FCherries%2F3D%2Fcherries_3d.png&name=1&owner=1&pattern=Transparent&pulls=1&stargazers=1&theme=Auto)

**[Explore the docs »](https://liblaf.github.io/cherries/)**

[![Test](https://github.com/liblaf/cherries/actions/workflows/test.yaml/badge.svg)](https://github.com/liblaf/cherries/actions/workflows/test.yaml)
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

## ✨ Features

- **Typed experiment config**: use Pydantic settings models as function arguments, with CLI parsing inherited from `pydantic-settings`.
- **Path helpers that log themselves**: create `asset`, `input`, `output`, and `temp` paths once, then let Cherries flush existing files at run end.
- **Composable plugins**: forward params, metrics, metadata, and artifacts through ordered hooks with `before` and `after` constraints.
- **Built-in run profiles**: choose local debug snapshots or full Comet, Git, local, and logging integration for regular runs.
- **Artifact bundle expansion**: log VTK `.series` frames and optional mesh landmark files alongside their primary artifact.

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

`profile="debug"` keeps Comet disabled and Git commits off while still copying the entrypoint, logs, and logged artifacts into `.cherries/`. The default profile enables Comet, writes a Git summary, commits dirty changes, and logs the final Git SHA.

## 🧩 Plugin Model

Plugins subclass `liblaf.cherries.core.Plugin`, mark hook implementations with `liblaf.cherries.core.impl()`, and register on a `Run` or `PluginManager`. Hooks can return first results for getters, collect all non-`None` results for normal delegation, and keep running later plugins when one hook raises.

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

Copyright © 2025 [liblaf](https://github.com/liblaf). <br />
This project is [MIT](https://github.com/liblaf/cherries/blob/main/LICENSE) licensed.

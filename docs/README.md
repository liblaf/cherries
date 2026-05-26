# Cherries

Cherries is a small experiment runner for Python scripts. It gives each run a
typed configuration model, path helpers for artifacts, and a plugin pipeline for
Comet, Git, local snapshots, and Python logging.

```bash
uv add liblaf-cherries
```

## Quick Start

Declare a config model, create paths as model defaults, and hand the experiment
function to `cherries.main()`.

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

`main()` starts a profile, builds missing arguments from annotations, logs any
Pydantic models as parameters, runs sync or async callables, and always ends the
run. If the experiment raises, Cherries passes the exception to `Run.end()` and
then re-raises it.

## Paths and Artifacts

Path helpers resolve locations from the entrypoint-derived experiment directory:

- `cherries.asset("figs/loss.png")` resolves below the experiment directory.
- `cherries.input("raw.csv")` and `cherries.output("metrics.json")` resolve
  below the experiment `data/` directory.
- `cherries.temp("scratch.txt")` resolves below the experiment `temp/`
  directory.
- `mkdir=True` creates the parent directory before returning the path.

Helpers queue paths instead of logging immediately. At run end, existing paths
are sent to every plugin that implements the matching hook. Missing paths are
reported as warnings. Bundle handlers expand related files automatically: VTK
`.series` manifests include their frames, and mesh files such as `.vtu`, `.vtp`,
and `.stl` include an optional sibling `.landmarks.json`.

## Profiles

Profiles configure the process-global `Run`.

- `debug`: starts Comet in disabled mode, disables Git commits, and keeps local
  snapshots and logging enabled.
- `default`: starts Comet normally, writes a Git summary, commits dirty changes,
  logs the final Git SHA, and keeps local snapshots and logging enabled.

When `profile` is omitted, `DEBUG=1` selects `debug`; otherwise `PROFILE`
selects a named profile and defaults to `default`.

## Plugins

Plugins subclass `core.Plugin`, decorate hook implementations with
`core.impl()`, and register on a `Run` or `PluginManager`. Hook order is
topologically sorted from each implementation's `before` and `after`
constraints. One plugin failure is logged without preventing later plugins from
running.

Built-in plugins:

- `Logging`: initializes a run log file and mirrors metrics through
  `liblaf.logging`.
- `Local`: copies the entrypoint, logs, and artifacts into a timestamped
  `.cherries/` snapshot.
- `Git`: writes an experiment summary, optionally commits dirty changes, and
  records the final Git SHA.
- `Comet`: forwards params, metrics, metadata, and assets to Comet; Git-tracked
  assets are uploaded as remote assets at run end when possible.

## API Map

- [liblaf.cherries](reference/liblaf/cherries/README.md): public convenience
  functions, `BaseConfig`, `Run`, bundles, plugins, and profiles.
- [liblaf.cherries.core](reference/liblaf/cherries/core/README.md): run state,
  plugin registration, hook delegation, and the global run proxy.
- [liblaf.cherries.bundle](reference/liblaf/cherries/bundle/README.md):
  companion-file discovery for artifact bundles.
- [liblaf.cherries.plugins](reference/liblaf/cherries/plugins/README.md):
  built-in Comet, Git, local snapshot, and logging plugins.
- [liblaf.cherries.profiles](reference/liblaf/cherries/profiles/README.md):
  default/debug profile selection and initialization.

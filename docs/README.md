# Cherries

Cherries is a lightweight experiment runner for Python scripts. It gives each
run a typed configuration model, reproducible artifact paths, scalar metric
history, and a plugin pipeline for Comet, Git, local snapshots, and Python
logging.

```bash
uv add liblaf-cherries
```

## Quick Start

Declare a config model, create artifact paths as model defaults, and hand the
experiment function to `cherries.main()`.

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

`main()` starts a profile, builds missing arguments from defaults or
annotations, logs Pydantic models as parameters, runs sync or async callables,
and always ends the run. If the experiment raises, Cherries passes the exception
to `Run.end()` and then re-raises it.

## Execution Model

Cherries keeps one process-global `Run`. Profiles configure that run, register
plugins, and call `Run.start()` before your experiment body executes. During the
run, convenience functions such as `cherries.log_metric()` and
`cherries.output()` forward to the active run.

At shutdown, `Run.end()` records end metadata, flushes queued artifacts, and
calls plugin `end()` hooks. Plugin failures are logged, and later plugins still
receive the same hook.

## Paths and Artifacts

Path helpers resolve locations from the entrypoint-derived working directory:

- `cherries.input("raw.csv")` and `cherries.output("metrics.json")` resolve
  below the experiment `data/` directory.
- `cherries.temp("scratch.txt")` resolves below the experiment `tmp/`
  directory.
- `mkdir=True` on `output()` and `temp()` creates the parent directory before
  returning the path.

`input()` logs immediately because inputs should already exist. `output()` and
`temp()` queue paths and flush them at run end, so experiments can create files
after configuration is built. Missing primary paths are reported as warnings.
Bundle handlers expand related files automatically: VTK `.series` manifests
include their required frames, and mesh files such as `.vtu`, `.vtp`, and `.stl`
include an optional sibling `.landmarks.json`.

## Metrics and Parameters

Use `log_metric()` for one scalar value and `log_metrics()` for a batch. Nested
metric mappings are flattened with `/`, so `{"train": {"loss": 0.4}}` becomes
`train/loss`. Metrics are stored as in-memory series and returned as Polars
dataframes with `name`, `value`, `step`, and `time` columns.

Parameters and metadata use the same flattening convention internally. Their
summary views are expanded back into nested dictionaries.

## Profiles

Profiles configure the process-global `Run`.

- `debug`: starts Comet in disabled mode, disables Git commits, and keeps local
  snapshots and logging enabled.
- `default`: starts Comet normally, writes a Git summary, commits dirty changes,
  logs the final Git SHA, and keeps local snapshots and logging enabled.

When `profile` is omitted, `DEBUG=1` selects `debug`; otherwise `PROFILE`
selects a named profile and defaults to `default`.

## Run Identity

The entrypoint path gives each run its default name. Cherries strips structural
`exp/` and `src/` path segments, removes the Python suffix, and uses the result
as the display name. For example,
`exp/2026/06/01/demo/src/10-main.py` becomes
`2026/06/01/demo/10-main`.

Set `CHERRIES_NAME` when a run needs a human-readable name. The display name is
used as-is for metadata and Comet, while the local snapshot key appends a
filesystem-safe slug to the timestamp. Set `CHERRIES_TAGS` to a comma-separated
list such as `debug,smoke` to attach tags to the run summary and Comet
experiment.

The local plugin writes snapshots below `.cherries/runs/<run-key>/`. The run key
contains the stripped entrypoint path plus a start timestamp, so repeated runs of
the same script do not overwrite each other.

## Plugins

Plugins subclass `core.Plugin`, decorate hook implementations with
`core.impl()`, and register with `run.plugins.register(...)`. Hook order is
topologically sorted from each implementation's `before` and `after`
constraints. One plugin failure is logged without preventing later plugins from
running.

Built-in plugins:

- `Logging`: initializes a run log file and mirrors metrics through Python
  logging.
- `Local`: copies the entrypoint, logs, and artifacts into a timestamped
  `.cherries/` snapshot.
- `Git`: optionally commits dirty changes and records the final Git SHA.
- `Comet`: starts a Comet run and forwards params, metrics, and metadata.

## API Map

- [liblaf.cherries](reference/liblaf/cherries/README.md): public convenience
  functions, `BaseConfig`, `Run`, bundles, plugins, and profiles.
- [liblaf.cherries.core](reference/liblaf/cherries/core/README.md): run state,
  plugin registration, hook delegation, and the global run proxy.
- [liblaf.cherries.core.assets.bundle](reference/liblaf/cherries/core/assets/bundle/README.md):
  companion-file discovery for artifact bundles.
- [liblaf.cherries.plugins](reference/liblaf/cherries/plugins/README.md):
  built-in Comet, Git, local snapshot, and logging plugins.
- [liblaf.cherries.profiles](reference/liblaf/cherries/profiles/README.md):
  default/debug profile selection and initialization.

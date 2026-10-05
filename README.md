<div align="center" markdown>
<a name="readme-top"></a>

![Cherries](https://socialify.git.ci/liblaf/cherries/image?description=1&forks=1&issues=1&language=1&logo=https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Ffluentui-emoji%2Frefs%2Fheads%2Fmain%2Fassets%2FCherries%2F3D%2Fcherries_3d.png&name=1&owner=1&pattern=Transparent&pulls=1&stargazers=1&theme=Auto)

**[Explore the docs »](https://liblaf.github.io/cherries/)**

[![Test](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml/badge.svg)](https://github.com/liblaf/cherries/actions/workflows/python-test.yaml)
[![PyPI - Version](https://img.shields.io/pypi/v/liblaf-cherries?logo=PyPI&label=PyPI)](https://pypi.org/project/liblaf-cherries)
[![Python](https://img.shields.io/pypi/pyversions/liblaf-cherries?logo=Python)](https://pypi.org/project/liblaf-cherries)

</div>

## What Cherries does

Cherries records ordinary Python experiments in a local, content-addressed store.
A successful `cherries.main(main)` run stages inputs and declared outputs in a
fresh work directory, captures source and runtime evidence, seals a small record
and manifest, and stores retained bytes once by SHA-256. It does not require a
background service or create Git commits. Comet is opt-in with `CHERRIES_COMET=1`;
its SDK is not loaded otherwise.

Use a separate experiment Git repository for authored studies. Keep Apple and
Melon there as submodules; keep generated run payloads in the configured Cherries
store. Git LFS is for curated fixtures and selected reviewable assets, not every
output, checkpoint, or log.

## Install and configure

The local recorder currently supports Linux with Python 3.12 or newer.

```bash
uv add liblaf-cherries
```

Place settings at the experiment repository root. `cherries.local.toml` is useful
for a machine-specific data volume and can stay Git ignored.

```toml
# cherries.toml
[collection]
id = "<collection-uuid>"

[capture]
roots = ["libs/apple", "libs/melon", "tools"]

[execution]
failure_payload = "discard"

[archive.main]
path = "/archive/cherries/phace-exp"
```

```toml
# cherries.local.toml
[collection]
storage = "/data/cherries/phace-exp"
```

`CHERRIES_STORAGE` overrides `collection.storage`. Initialize a collection
explicitly before sharing it with other machines:

```bash
cherries --project-dir . --storage /data/cherries/phace-exp init \
  --collection-id "<collection-uuid>"
```

Choose a local data volume through `collection.storage` or `--storage`.
Configure `archive.main.path` before using archive or sync with `--remote main`.

## Run a sealed experiment

Keep module scope passive: do not read experiment data, create outputs, initialize
a solver, or call Cherries asset, metric, parameter, or step helpers until
`main`. Config defaults are raw source strings or paths.

```python
from liblaf import cherries


class Config(cherries.BaseConfig):
    mesh: str = "sha256:<full-digest>"
    steps: int = 200


def main(cfg: Config) -> None:
    mesh = cherries.input(cfg.mesh, name="mesh.vtu")
    output = cherries.output("solution.txt")
    cherries.temp("solver-cache")
    output.write_text(f"{mesh.name}: {cfg.steps}\n")
    cherries.log_metric("steps", cfg.steps)


if __name__ == "__main__":
    cherries.main(main)
```

Run the script normally; `BaseConfig` accepts kebab-case flags.

```bash
uv run python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
```

`input()` accepts a local path, a full `sha256:` asset ID, a `sha256-tree:`
bundle ID, or `run:<record-id>/<logical-path>`. It copies verified bytes into
`work/<id>/inputs` and registers lineage before use. `output()` returns a path
under `work/<id>/outputs`; every declared output must exist at completion.
`log_output()` imports an already-created external file. `temp()` uses disposable
`work/<id>/scratch` and is not retained by default.

Cherries captures the entry script, Git HEAD, binary working-tree diff, selected
untracked source, runtime facts, resolved parameters, inputs, logs, metrics, and
outputs. Capture begins after normal module imports, so it records source at the
`main` boundary and does not claim replay verification. An execution exception
keeps a diagnostic event and may discard only the unsealed work payload. A missing
output or recording failure leaves the work stage for recovery and raises an error.

## Inspect, archive, and restore

All commands are foreground operations. Add `--json` before the subcommand for
machine-readable output.

```bash
cherries --storage /data/cherries/phace-exp browse --quality unreviewed
cherries --storage /data/cherries/phace-exp browse --failed
cherries --storage /data/cherries/phace-exp show <record-id>
cherries --storage /data/cherries/phace-exp read <record-id> RUN.md
cherries --storage /data/cherries/phace-exp path <record-id> outputs/solution.txt
cherries --storage /data/cherries/phace-exp path --release <lease-id>
cherries --storage /data/cherries/phace-exp archive <record-id> --remote /archive/cherries --evict
cherries --storage /data/cherries/phace-exp restore <record-id> --remote /archive/cherries
```

`path` materializes the selected record file only and creates a durable read lease;
release it when finished. `restore` verifies and materializes a complete record
view. `archive` verifies object bytes, uploads the complete closure, and writes
the remote commit marker last. `--evict` only releases an eligible local view
after remote verification; it never removes canonical bytes merely because one
logical record was archived.

A local-directory remote has an atomic filesystem boundary. A generic rclone
remote requires `--coordinated`, which is an explicit assertion that an external
publisher serializes the collection; Cherries does not invent a marker-file lock
or stale-owner takeover. Metadata-only synchronization is available through
`cherries sync --remote ... [--coordinated]`.

`sync` publishes SHA-bound collection control, sealed receipts, events, and a
payload-free checkpoint marker last. Checkpoint import can merge receipt metadata
and lineage; it does not establish that payload objects are remotely available.
Failed attempts appear only in local `browse --failed`; they are not remotely
published or imported.

For Python follow-up work, use a closeable reader hold:

```python
with cherries.open_run("<record-id>") as saved:
    path = saved.path("outputs/solution.txt")
```

Pass `workspace=Path("analysis/compare")` to attach the source to an existing
analysis workspace. Close the accessor or use a context manager in either mode:
its temporary reader hold protects active reads even if the workspace is closed.
The workspace's own source hold remains until `cherries analysis close`.

`cherries rerun <record-id> --prepare-only --workspace replay/<record-id>`
reconstructs a workspace from the saved project/submodule HEADs, binary patches,
selected untracked source, and recorded input mapping. It requires the captured
local Git bases and a source-stable experiment receipt. Omit `--prepare-only` to
execute with `uv run` (using `--locked` when `uv.lock` is saved). It creates a
new attempt and leaves `replay_verified` false until scientific checks establish
replay. Close a retained prepared workspace with `cherries rerun --close <path>`.

## Review and follow-up analysis

Successful records start `unreviewed`. Review, labels, and retention flags are
append-only metadata rather than changes to the sealed receipt.

```bash
cherries review <record-id> --quality good --note "Useful comparison"
cherries label add <record-id> mouthopen promising
cherries mark <record-id> --important
cherries mark <record-id> --keep-local
cherries analysis new analysis/compare --source <record-id>
cherries analysis save analysis/compare --output out/figure.png --used-in weekly/2026-10-05
cherries analysis close analysis/compare
```

An analysis workspace holds its source records while it is open. Saving it creates
a lightweight dependent record. `RUN.md` and `analysis.json` retain their names;
workspace `src/...` becomes `source/...`, and explicitly selected `out/...` files
become `outputs/...` in the saved record. Read saved scripts and figures using
those record-relative paths, including for existing saved analyses. A record
with dependents cannot be discarded. Local single-machine maintenance is explicit
and receipt-bound:

```bash
cherries maintenance pause
cherries discard <record-id> --plan
cherries discard --apply <plan-path>
cherries prune --plan
cherries prune --apply <plan-path>
cherries maintenance resume <pause-token>
```

Pause freezes reference creation. It fails closed with active or pending work,
legacy provenance, or foreign participants. Plans bind to the pause receipt and
local inventory; an inventory change requires a new plan. This does not implement
remote or distributed deletion.

## Development

```bash
uv run pytest
mise run lint
mise run docs:build
```

See [docs/README.md](docs/README.md) for the detailed runtime and CLI contract,
and [docs/design/run-records.md](docs/design/run-records.md) for the remaining
distributed-maintenance and replay design.

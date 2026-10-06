# Cherries records

Cherries is a foreground Python experiment recorder. A run owns a UUID work
folder on a configured data volume, then seals retained files into a local
SHA-256 content-addressed store. It has no daemon and does not require a full
local metadata mirror to browse remote records.

## Repository boundary

Use an experiment superproject for authored work:

```text
phace-exp/
  cherries.toml  pyproject.toml  uv.lock
  libs/apple/                    # Git submodule
  libs/melon/                    # Git submodule
  exp/YYYY/mm/dd/study/
    src/  configs/  fixtures/  docs/  analysis/
```

Scripts, configs, reports, submodule gitlinks, and small curated fixtures belong
in Git. LFS is limited to deliberately curated fixtures or selected reviewable
assets. Generated input copies, meshes, logs, checkpoints, and outputs belong
outside Git in the Cherries store.

```text
<storage>/
  objects/sha256/ab/<digest>     # immutable raw file, stored once
  objects/sha256-tree/ab/<digest># canonical directory descriptor
  records/<run-id>/              # record.json, manifest.json, complete.json
  work/<run-id>/                 # active, writable staging area
  runs/<run-id>/                 # optional materialized ordinary-file view
  metadata/events/<machine-id>/  # append-only review, label, hold, location events
  pending/                       # active work roots and parents
```

`cherries.toml` and `cherries.local.toml` are discovered from the current
directory upwards. Local settings override repository settings. `CHERRIES_STORAGE`
takes precedence over `collection.storage`.

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
# cherries.local.toml, typically ignored by Git
[collection]
storage = "/data/cherries/phace-exp"
```

The local recorder currently supports Linux with Python 3.12 or newer. Choose a
data volume through `collection.storage` or `--storage`; `--remote main` requires
an explicitly configured `archive.main.path`.

## Python contract

Run ordinary Python. Keep imports and definitions passive: import-time data I/O,
solver/GPU setup, random initialization, and calls to Cherries asset, metric,
parameter, or step helpers belong inside `main`.

```python
from liblaf import cherries


class Config(cherries.BaseConfig):
    mesh: str = "sha256:<full-digest>"
    steps: int = 200


def main(cfg: Config) -> None:
    mesh = cherries.input(cfg.mesh, name="mesh.vtu")
    result = cherries.output("result.txt")
    scratch = cherries.temp("solver")
    result.write_text(f"{mesh} {scratch} {cfg.steps}\n")


if __name__ == "__main__":
    cherries.main(main)
```

`BaseConfig` parses normal kebab-case Python arguments before recording starts.
CLI help and invalid configuration exit without creating a run or work folder.
`main()` creates a fresh
local work directory at the collection's `work/<id>/`, captures source/runtime
evidence, invokes the callable once,
and seals the result only after declared outputs were written. It does not
self-relaunch, sandbox, bootstrap, or automatically Git commit. `CHERRIES_COMET=1`
enables Comet; it is disabled by default and its SDK is not loaded otherwise.

Complete asynchronous native operations and all work-folder writes before
`main` returns. Cherries waits for new Python-managed threads, including daemon
threads, but cannot join or track foreign native threads. Native housekeeping
threads do not block sealing; synchronizing native library or GPU work remains
the experiment's responsibility.

Asset helpers require an active run:

- `input(source, name=..., source_run=...)` accepts a local file/directory, full
  `sha256:` ID, `sha256-tree:` ID, or `run:<id>/<logical-path>`. It verifies and
  copies or materializes into `inputs/`, records the chosen producer, and
  registers a parent before reading.
- `output(relative_path)` declares a required output under `outputs/`.
- `log_output(existing_path, name=...)` copies an external output into `outputs/`.
- `temp(relative_path)` returns an unretained path under `scratch/`.

A plain asset ID identifies file bytes. A `sha256-tree:` ID identifies a canonical
inventory and its companion files. Equal file bytes deduplicate; Cherries makes
ordinary independent copies when materializing an input or view.

Treat staged inputs as immutable for the duration of `main`. Cherries detects a
modified staged input, leaves the work directory as an incomplete record, and
raises instead of sealing misleading provenance. Scientific non-finite metric
values are retained as the explicit strings `NaN`, `Infinity`, or `-Infinity` for
manual review; they do not silently become JSON null or a success claim.

At run start and end Cherries records entry source, Git HEADs, binary diffs,
selected untracked source files, and runtime facts. This is capture at the main
boundary: it reports whether the source fingerprint stayed stable, but it never
claims full replay verification. Git bases must remain available to replay source
outside Cherries.

On success, the store writes objects, stages `record.json`, `manifest.json`, and
`complete.json`, fsyncs and renames that record directory, then appends a sealed
event. On a normal execution error it writes diagnostic metadata and, with the
default `failure_payload = "discard"`, removes only the unsealed payload. A
missing declared output or sealing failure preserves the work stage and raises.

## Foreground CLI

Global options precede the command:

```bash
cherries --storage /data/cherries/phace-exp init --collection-id <uuid>
cherries --storage /data/cherries/phace-exp --json browse --quality unreviewed
cherries --storage /data/cherries/phace-exp browse --label mouthopen
cherries --storage /data/cherries/phace-exp browse --asset sha256:<digest>
cherries --storage /data/cherries/phace-exp browse --used-in weekly/2026-10-05
cherries --storage /data/cherries/phace-exp browse --failed
cherries --storage /data/cherries/phace-exp browse --search mouthopen
cherries --storage /data/cherries/phace-exp show <id>
cherries --storage /data/cherries/phace-exp read <id> RUN.md
cherries --storage /data/cherries/phace-exp path <id> outputs/result.txt
cherries --storage /data/cherries/phace-exp --json path <id> legacy/data/example.vtu
cherries --storage /data/cherries/phace-exp path --release <lease-id>
cherries --storage /data/cherries/phace-exp restore <id> --remote /archive/cherries
cherries --storage /data/cherries/phace-exp archive <id> --remote /archive/cherries --evict
cherries --storage /data/cherries/phace-exp sync --remote /archive/cherries
cherries --storage /data/cherries/phace-exp index rebuild --remote /archive/cherries
```

`browse` reports each record's latest review quality. `--used-in` returns the
named meeting/weekly analyses and their direct source parents; `--search` matches
record name, kind, legacy origin, and migrated legacy source. `path` creates a durable read hold unless
it is associated with an analysis workspace. It materializes a declared file or
directory plus required `.series` companions, or a whole `sha256-tree` bundle
only when that tree is declared by the selected record. Tree descriptors preserve
declared empty directories. `restore` verifies and materializes the complete
record under a temporary restore hold, then marks it as a locally restored
resident view.

A companion bundle's primary path returns a file, with companion files beside
it. Tree inputs restore at their recorded staged path and retain empty folders.

The JSON result of `path` contains its lease ID. Keep the selected raw path only
while needed, then pass that exact ID to `path --release`; a lease holds the run
against eviction. Use the same form for a migrated path such as
`legacy/data/example.vtu`.

Python follow-up code can use the same closeable access boundary:

```python
from liblaf import cherries

with cherries.open_run("<record-id>") as saved:
    result = saved.path("outputs/result.txt")
    print(saved.record["record"]["execution"], result.read_text())
```

`open_run` keeps a reader hold until `close()` or the context exits. With
`workspace=Path("analysis/compare")`, it attaches that record to the existing
analysis workspace hold; `cherries analysis close` releases it. Its `path()` has
the same contained-file/directory and `.series`-companion behavior as the CLI.

`cherries rerun <id> --prepare-only --workspace replay/<id>` reconstructs a
fresh project from saved Git HEADs, binary diffs, selected untracked files, the
captured entrypoint, and recorded input mapping. It requires captured local Git
bases and a source-stable experiment receipt. Without `--prepare-only`, it runs
through `uv run` (using `--locked` when `uv.lock` exists); a prepared workspace
keeps its reader hold until `cherries rerun --close <workspace>`. Rerun is a new
attempt and cannot claim `replay_verified` before scientific checks establish it.

For a remote rclone path, add `--coordinated` only when an external, real
publisher serializes writes for the whole collection. Rclone does not itself
provide portable create-if-absent publication. Cherries uploads and read-back
verifies each immutable object, publishes record metadata, then writes the remote
`commit.json` marker last. It does not use a marker lock or automatically take
over a possibly stale publisher. A local directory remote uses its filesystem's
atomic publication boundary.

Payload closure includes manifest files and explicit asset bindings, including
bundle descriptors and their members. Parent manifest and record digests are
control evidence, so they are verified as metadata rather than uploaded as CAS
payloads. Digest-shaped parameter values are not asset declarations.

`archive --evict` requires verified remote publication and removes only an
eligible materialized local view. A view needed by another resident record,
active work, a read/analysis hold, or `--keep-local` remains local. `--important`
protects logical retention; it is separate from local view eviction. A shared tree
object keeps its complete member closure while any resident local record needs it.

If the archive is verified and committed but its local verification annotation
cannot be saved, `archive` returns the committed location with a `warnings`
entry and exits successfully. `--evict` skips that record and reports
`eviction_skipped`, preserving its local bytes. A remote publication error still
fails the command.

`sync` publishes SHA-bound control metadata, sealed receipts, events, and a
payload-free checkpoint marker last. Checkpoint import can merge remote receipt
metadata and the selected record's required ancestor graph, but it never
establishes remote payload availability.
Selected restore and metadata import install only that lineage's records and
event history, including updates for ancestors already present locally. Global
metadata sync still imports the whole collection. The current checkpoint format
requires reading and validating all checkpoint-bound events before installation;
unrelated event files are verified but not installed by a selected import.
`browse --failed` lists local failed-attempt diagnostics only; attempts are not
published or imported through remote metadata sync.

## Review, lineage, and analysis

### Living run documentation

The [current experiment skill](skills/run-cherries-experiments/SKILL.md) tells
Codex to maintain study notes and per-run memories during substantive discussion,
including evidence, decisions, changing interpretations, and open questions.
Editable Markdown lives in the experiment repository at
`exp/YYYY/mm/dd/study/docs/runs/<run-id>.md`.

```bash
cherries note <id> --file exp/YYYY/mm/dd/study/docs/runs/<id>.md
cherries --json show <id>
```

Each invocation of `note` appends the complete Markdown version, even when the
text is unchanged. Codex compares it with the latest saved memory before
invoking the command to avoid redundant revisions. `show` returns current
`projection.notes`, reviews, and links alongside the frozen receipt and manifest.
Codex reads the latest saved memory when resuming work and can recover a missing
local document from the notes. Ordinary notes do not create dependent records,
holds, or a new retention rule. Sealed experiment files stay unchanged; explicit
comparisons and promoted outputs use saved analyses.

### Review and saved analysis

Every successful record starts with subjective quality `unreviewed`; execution,
validation, and review are different fields.

```bash
cherries review <id> --quality good --note "Useful for weekly comparison"
cherries label add <id> mouthopen promising
cherries label remove <id> promising
cherries mark <id> --important
cherries mark <id> --no-important
cherries mark <id> --keep-local
cherries note <id> --file findings.md
cherries link <id> --git <commit>
cherries analysis new analysis/compare --source <id>
cherries analysis source analysis/compare add <id>
cherries analysis save analysis/compare --output out/figure.png --used-in weekly/2026-10-05
cherries analysis close analysis/compare
```

Review, label, mark, hold, and location changes are append-only metadata events
that synchronize independently of sealed records; notes and Git links use the
same event transport. A saved analysis becomes a
lightweight dependent record and protects each source. `analysis save` uses the
following mapping for workspace files:

| Workspace path | Saved record path |
| --- | --- |
| `RUN.md` | `RUN.md` |
| `analysis.json` | `analysis.json` |
| `src/...` | `source/...` |
| Selected `out/...` files | `outputs/...` |

For example, retrieve `src/compare.py` from an existing or new saved analysis
with `cherries read <analysis-id> source/compare.py`; retrieve selected
`out/figure.png` with `cherries path <analysis-id> outputs/figure.png`.
An analysis is a record of interpretation, not a strict solver replay.

Repeated analysis saves retain the name, increment a revision number, and link
the new record to the previous revision and source runs. The editable workspace
tracks `latest_record`; source projections expose the saved analysis links.
Closing releases workspace holds while keeping the Markdown editable for a later
save. Use this retention workflow for outputs that depend on their sources.

Imported legacy folders are additive immutable records with deliberately
incomplete provenance. Their legacy source/name metadata is searchable, but they
do not become source-stable experiments, replayable records, or authorization for
maintenance merely by being imported.

Local single-machine maintenance uses an explicit pause receipt and saved plan:

```bash
cherries maintenance pause
cherries discard <id> --plan
cherries discard --apply <plan-path>
cherries prune --plan
cherries prune --apply <plan-path>
cherries maintenance resume <pause-token>
```

Pause freezes reference creation and fails closed with work/pending intents,
legacy provenance, or foreign participants. A plan binds to its pause receipt and
inventory digest; any inventory change invalidates it. This does not implement
remote or distributed maintenance. A retired/tombstoned child remains a strict
dependent and still blocks retirement of its parent.

## Current limits

The current runtime implements local sealing, CAS deduplication, source capture,
metadata merge, archive/restore, partial materialization, reviews, labels, and
lightweight analysis records. The future design in
[run-records.md](design/run-records.md) describes broader replay and fleet-GC
requirements. Automatic environment reconstruction beyond saved source and lock
files, remote checkpoint compaction, remote attempt transfer, and destructive
multi-machine GC are not available commands.

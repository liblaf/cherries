---
name: run-cherries-experiments
description: Run and analyze liblaf.cherries experiments, maintain evolving per-run documentation during discussions, and manage immutable local or remote CAS records.
---

# Run Cherries Experiments

Use this skill for Cherries experiments and saved records. Read the Cherries
checkout's `docs/README.md` before relying on a command; installed versions may
not yet include every documented capability.

## Repository boundary

Work in the separate experiment superproject, for example:

```text
phace-exp/
  cherries.toml  pyproject.toml  uv.lock
  libs/apple/  libs/melon/       # Git submodules
  exp/YYYY/mm/dd/study/
    src/  configs/  fixtures/  docs/  analysis/
```

Keep authored study source, configuration, reports, curated fixtures, and
submodule gitlinks in Git. Use LFS only for selected curated/reviewable assets.
Generated inputs, outputs, logs, meshes, and checkpoints belong in the Cherries
store, never in Apple or Melon repositories and never in broad LFS patterns.

Use a configured local data volume, not `/tmp`:

```toml
# cherries.local.toml (normally Git ignored)
[collection]
storage = "/data/cherries/phace-exp"
```

Initialize a new collection explicitly:

```bash
cherries --project-dir . --storage /data/cherries/phace-exp init \
  --collection-id "<collection-uuid>"
```

Read the project's settings to resolve its local storage and archive targets;
do not assume a machine-specific path or a published experiment Git ref.
Use `--storage` to override local storage. Remote archive/sync through
`--remote main` requires an explicitly configured `archive.main.path`.
The local recorder currently supports Linux with Python 3.12 or newer.

## Sealed daily experiment

Run normal Python or `uv run python`; no bootstrap, relaunch, daemon, manual
save, or automatic Git commit is involved.

```python
from liblaf import cherries


class Config(cherries.BaseConfig):
    mesh: str = "sha256:<full-digest>"  # raw source declaration
    steps: int = 200


def main(cfg: Config) -> None:
    mesh = cherries.input(cfg.mesh, name="mesh.vtu")
    result = cherries.output("solution.txt")
    cherries.temp("solver-cache")
    result.write_text(f"{mesh.name}: {cfg.steps}\n")
    cherries.log_metric("steps", cfg.steps)


if __name__ == "__main__":
    cherries.main(main)
```

Keep module scope passive. Do not read data, instantiate a solver/GPU context,
create random experiment state, parse live inputs, or call Cherries asset, metric,
parameter, or step helpers outside `main`. Config defaults must be raw strings or
paths; helpers require an active run. Invoke it as ordinary Python, preserving
original arguments:

```bash
uv run python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
```

`BaseConfig` accepts kebab-case flags; help and invalid configuration exit before
recording starts. Set `CHERRIES_COMET=1` only for intended
Comet observability; it is disabled by default and its SDK is not loaded otherwise.

Complete asynchronous native operations and all work-folder writes before
`main` returns. Cherries waits for new Python-managed threads, including daemon
threads, but cannot join or track foreign native threads. Native housekeeping
threads do not block sealing; explicitly synchronize native library or GPU work.

`input()` accepts a local path, complete `sha256:` file ID, `sha256-tree:` bundle
ID, or `run:<record-id>/<logical-path>`. It verifies and stages an independent
copy under `inputs/`, records the selected producer, and registers lineage before
reading. Pass `source_run=<record-id>` to restrict a digest's provenance.
`output()` declares a required path under `outputs/`; `log_output()` copies an
existing external output there. `temp()` returns a disposable `scratch/` path.

Never modify staged inputs during `main`: detection leaves incomplete work and
raises instead of sealing it. Non-finite scientific metric values are retained
for review as `NaN`, `Infinity`, or `-Infinity` strings.

Cherries captures entry source, HEADs, binary diffs, selected untracked source,
runtime evidence, parameters, input bindings, logs, metrics, and declared
outputs. It captures after ordinary imports at the `main` boundary, so record
source stability but never claim `replay_verified`. Keep referenced Git bases
available. A successful run seals canonical SHA-256 objects and a small immutable
record. A missing declared output or recording error retains the work stage. An
execution failure records diagnostics and may discard only an unsealed local
payload with no dependency or hold.

## Living experiment documentation

Automatically maintain experiment notes during experiment sessions. This is a
standing workflow request; do not wait for a separate "write docs" instruction.
At the start of a session, read the study's `RUN.md` and relevant run memories
before proposing work. Carry forward decisions, unsuccessful approaches,
uncertainties, and the reasons behind the current plan.

Before a run is sealed, keep its question, protocol, and discussion in the
study's `RUN.md`. For a saved run, maintain one editable Markdown document at
`exp/YYYY/mm/dd/study/docs/runs/<RUN-ID>.md`. In phace-exp, seed it from
`templates/run-memory.md`; replace template prompts with actual evidence.
Include the exact run ID, command/configuration, input and output references,
observations, current interpretation, decisions, open questions, next steps,
and a short dated history of meaningful changes. Use only relevant sections.

Update notes after substantive discussion, new results, decisions, corrections,
or changes of direction, and before the final response or session handoff.
Preserve measured facts; explain and mark superseded interpretations when
conclusions change. Summarize useful reasoning rather than copying the chat.
For a failed execution with no saved run, record diagnostics in study notes.

Attach each changed document version to the saved run locally:

```bash
uv run cherries note <RUN-ID> --file exp/YYYY/mm/dd/study/docs/runs/<RUN-ID>.md
uv run cherries --json show <RUN-ID>
```

The full Markdown is retained as an append-only annotation. `show` includes
`projection.notes`; the latest entry whose `value` starts with `# Run memory:`
is the saved memory, and earlier versions remain available. Recover a missing
local document from it. If concurrent sessions left divergent versions, read
both and consolidate their evidence and open questions into a new revision.
Compare with the last saved memory before invoking `note` and skip unchanged
documents. The CLI appends a revision on every invocation; it does not suppress
duplicates.

These ordinary memories create no dependent record or retention hold, so taking
notes preserves manual discard eligibility. Keep the original sealed `RUN.md`
and receipt intact. Explicit comparisons, figures, or meeting outputs use the
analysis workflow below and protect their source runs. Do not infer automatic
Git commits or remote publication from permission to maintain documentation.

## Inspect records and archive

Put global options before the command. Use `--json` when output becomes input to
a script.

```bash
cherries --storage /data/cherries/phace-exp --json browse --quality unreviewed
cherries --storage /data/cherries/phace-exp browse --failed
cherries --storage /data/cherries/phace-exp browse --label mouthopen
cherries --storage /data/cherries/phace-exp browse --asset sha256:<digest>
cherries --storage /data/cherries/phace-exp browse --search mouthopen
cherries --storage /data/cherries/phace-exp browse --used-in weekly/2026-10-05
cherries --storage /data/cherries/phace-exp show <record-id>
cherries --storage /data/cherries/phace-exp read <record-id> RUN.md
cherries --storage /data/cherries/phace-exp path <record-id> outputs/solution.txt
cherries --storage /data/cherries/phace-exp --json path <record-id> legacy/data/example.vtu
cherries --storage /data/cherries/phace-exp path --release <lease-id>
cherries --storage /data/cherries/phace-exp archive <record-id> --remote /archive/cherries --evict
cherries --storage /data/cherries/phace-exp restore <record-id> --remote /archive/cherries
```

`browse` uses the latest review quality; `--used-in` includes the named analysis
and its direct source parents. `--search` matches name, kind, legacy origin, and
migrated legacy source.
`path` materializes a declared file or directory plus required `.series`
companions, and creates a durable read lease. A `sha256-tree` must be declared by
the selected record; it restores its full topology, including declared empty
directories. `restore` verifies the full record under a temporary restore hold,
then creates a locally restored resident view.

The JSON `path` result contains a lease ID; release that exact ID when inspection
ends. This applies equally to a migrated raw path such as `legacy/data/example.vtu`.

For Python follow-up work, use a closeable reader hold:

```python
with cherries.open_run("<record-id>") as saved:
    result = saved.path("outputs/solution.txt")
```

Pass `workspace=Path("analysis/compare")` to attach the source to an existing
analysis workspace hold. In either mode, close the accessor or use a context
manager: its temporary reader hold protects active reads even if the workspace
is closed. The workspace's own hold remains until `cherries analysis close`.

`cherries rerun <id> --prepare-only --workspace replay/<id>` reconstructs a
fresh workspace from saved Git HEADs, binary diffs, selected untracked source,
captured entrypoint, and input mapping. It requires local captured Git bases and
a source-stable experiment receipt. Without `--prepare-only`, it executes that
workspace through `uv run` (with `--locked` when `uv.lock` exists). It makes a
new attempt; `replay_verified` stays false until scientific checks establish it.
Close a prepared workspace with `cherries rerun --close <workspace>`.

Archive is foreground only. It verifies each local object, publishes the complete
closure, read-back verifies bytes, and publishes remote `commit.json` last. A
local-directory remote has an atomic filesystem boundary. Generic rclone remotes
require `--coordinated`, which asserts real external serialization of collection
publishers; do not use a marker-file lock or stale-owner takeover. Use
`cherries sync --remote REMOTE [--coordinated]` to transfer append-only metadata.
Sync writes SHA-bound control metadata, events, and a payload-free checkpoint
marker last. Checkpoint import merges selected receipt metadata with its required
ancestor graph only; it does not prove remote payload availability.
Selected restore and import install only that lineage's events, including updates
for already-local ancestors. All checkpoint-bound event proofs are still verified
before installation. Global metadata sync retains its collection-wide scope.
Failed attempts in `browse --failed` are local diagnostics and are never published
or imported.

`--evict` releases only an eligible materialized local view after verification.
Other resident records, active work, reader/analysis holds, and `--keep-local`
block it. `--important` protects logical retention rather than a local view. A
shared tree object keeps its full member closure while any resident local record
needs that tree.

## Review and lightweight analysis

A successful run starts `unreviewed`. Review is subjective and separate from
execution or scientific validation. Labels and reviews append metadata events;
they do not change immutable receipts or CAS objects, and `bad` never auto-
discards a successful run.

```bash
cherries review <id> --quality good --note "Useful comparison"
cherries label add <id> mouthopen promising
cherries label remove <id> promising
cherries mark <id> --important
cherries mark <id> --keep-local
cherries note <id> --file findings.md
cherries link <id> --git <commit>
cherries analysis new analysis/compare --source <id>
cherries analysis save analysis/compare --output out/figure.png --used-in weekly/2026-10-05
cherries analysis close analysis/compare
```

Use a current development environment, ParaView, or another interactive tool for
follow-up work. Add selected sources to the analysis; while open, its workspace
holds them. Save `RUN.md`, `analysis.json`, `src/`, and only explicit `out/...`
outputs. In the sealed record, `RUN.md` and `analysis.json` keep their names,
workspace `src/...` is stored as `source/...`, and selected `out/...` files are
stored as `outputs/...`. Use these saved paths for retrieval, including existing
analysis records; for example, `cherries read <analysis-id> source/compare.py`
and `cherries path <analysis-id> outputs/figure.png`.
Save ParaView settings and displayed asset references when useful. A
saved analysis is a lightweight dependent record and protects every source; it
does not promise strict solver replay. Notes and Git links are append-only events
and synchronize with the other metadata.

Legacy imports are additive immutable records with incomplete provenance. Their
legacy source/name is searchable, but they are not source-stable experiments,
replayable records, or authorization for maintenance.

Local single-machine maintenance requires a pause receipt and saved plan:

```bash
cherries maintenance pause
cherries discard <id> --plan
cherries discard --apply <plan-path>
cherries prune --plan
cherries prune --apply <plan-path>
cherries maintenance resume <pause-token>
```

Pause freezes reference creation and fails closed with active/pending work,
legacy provenance, or foreign participants. Plans bind to the local pause receipt
and inventory. This does not authorize remote or distributed deletion; never
replace it with rclone cleanup or remove a record with dependents. A retired child
still blocks its parent. Shared tree-object eviction protects its full closure
while any resident local record still needs it.

## Evidence and reporting

Report actual record IDs, commands, record/manifest evidence, generated asset
paths, and observed metrics. Distinguish an execution receipt, validation result,
subjective review, and replay claim. Do not call a work folder a saved record
until sealing succeeds, and do not describe a migration as complete without its
verified receipt and the migration owner’s confirmation.

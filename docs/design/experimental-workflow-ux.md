# Cherries workflow UX

Status: implementation and target UX, 2026-10-05. The local CAS runtime now
implements ordinary `cherries.main(main)` capture, active-run asset helpers,
record sealing, archive/restore, metadata merge, review/labels, materialization
leases, lightweight analysis records, `rerun`, payload-free metadata checkpoints,
and receipt-bound single-machine maintenance. The authoritative implemented
contract is [the user documentation](../README.md). This document still specifies
target work that is not available yet, including automatic environment
reconstruction, remote checkpoint compaction, remote attempt transfer, and
destructive fleet maintenance.

The daily flow is save first, review later. Cherries captures computation
evidence, supports lightweight follow-up work, and archives complete records
through rclone to a SHA-256 content-addressed store. Successful results start unreviewed. Keeping, reviewing, and using a
result are independent actions. Daily execution remains a normal Python command.

## Work locations

Use a separate experiment Git repository with Apple and Melon as submodules:

```text
experiments/
  pyproject.toml  uv.lock  cherries.toml
  libs/apple/  libs/melon/
  exp/2026/10/05/mouthopen/
    experiment.toml
    src/10-run.py
    configs/baseline.toml
    fixtures/
    docs/
    analysis/compare-neutral/
      analysis.toml
      src/10-compare.py
      RUN.md
      out/                        # ignored drafts; select outputs when saving
```

Authored scripts, configurations, reports, and optional small receipts belong
in Git. LFS holds curated fixtures and selected published assets. Local and
remote stores share this object, record, and metadata schema:

```text
<storage-root>/objects/sha256/ab/<full-digest>  # immutable raw blob, once
<storage-root>/records/<id>/       # record.json, manifest.json, RUN.md
<storage-root>/work/<id>/          # independent/reflinked active copies
<storage-root>/runs/<id>/          # optional ordinary materialized view/cache
<storage-root>/metadata/           # events and checkpoints
```

`work/<id>/inputs` and `outputs` are ordinary writable copies or reflinks, never
writable hardlinks into `objects`. Records map logical paths to asset IDs; they
are not permanent per-run payload copies. Bundle manifests are themselves
content-addressed `sha256-tree` inventories of child file hashes.

## Run an experiment

Initialize the local storage volume once, then execute the script normally:

```bash
cherries init --storage /data/cherries/research
python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
# Or use the project's uv environment:
uv run python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
```

Keep the usual imports, config, and function definitions, with this call at
the bottom of the script:

```python
if __name__ == "__main__":
    cherries.main(main)
```

`cherries.main(main)` is the in-process recording boundary. It allocates a UUID
work folder on the configured data volume, captures the entry script; each
relevant experiment repository and submodule's Git HEAD and combined binary
diff; selected untracked code copied separately; supplied configuration; and
runtime evidence.
It invokes `main` once. On success it imports retained payloads into canonical
objects, stages, fsyncs, and renames complete local record metadata, appends a
sealed event, then unregisters and reclaims disposable work. There is no default bootstrap, relaunch, sandbox,
daemon, or manual save step.

This is observed provenance at the `main` boundary: it cannot prove source state
already imported before the call. Record a source-stability flag and never claim
`replay_verified`. The Git base commit must remain obtainable for replay; the
record does not retain complete environment/build artifacts.

Asset helpers are active only inside `main`. Config defaults are raw strings or
paths and must not call `input`, `output`, or `temp` during class definition:

```python
class Config(cherries.BaseConfig):
    mesh: str = "sha256:<full-digest>"

def main(cfg: Config) -> None:
    mesh = cherries.input(cfg.mesh, name="mesh.vtu")
    result = cherries.output("solution.npz")
    scratch = cherries.temp("solver")
    # Read mesh, write result, and use scratch here.
```

`input` accepts a full `sha256:` file digest, a local path/source string, or an
optional `run:<id>/path` reference. It copies verified bytes to `work/inputs`.
`output` returns `work/outputs`; `log_output` copies an external result there;
and `temp` returns disposable `work/scratch`. A missing required output or a
storage failure yields `incomplete`, nonzero status, and a retained stage.

On exit zero and a complete recording contract, Cherries imports retained bytes
to CAS, publishes the manifest/record and sealed event, then reclaims work. It
reports its ID, execution outcome, validation outcome, and unreviewed review
state. Stdout/stderr, configuration, source, asset hashes, metrics, and runtime
evidence remain in records and objects. Execution failures keep a small receipt
and may discard only a stopped, unpinned, never-published, unsealed local leaf
payload with no dependent or hold.

```bash
cherries show <run-id> --json
cherries read <run-id> RUN.md
cherries path <run-id> outputs/solution.npz
cherries browse --asset sha256:<full-digest> --json
cherries rerun <run-id>
```

`show --json` includes retained output paths and their `asset_id` values.

`rerun` is a new attempt; it never mutates its source record. A Git commit is
optional navigation: record authored changes and submodule commits deliberately,
then associate it with `cherries link <run-id> --git <commit>`.

## Assets and provenance selection

The SHA-256 of file content is its `asset_id`, stored canonically at
`objects/sha256/<2hex>/<full-digest>`. Manifests and the catalog index each
asset by run, relative path, digest, and local-or-remote location. Identical
bytes share one object while retaining several producer records.

For a digest or unqualified asset reference, Cherries selects a complete local
producer first and otherwise a remote producer. It verifies bytes, records the
chosen producer run/path and all digests, and registers the parent edge before
the caller reads it. `source_run=<id>` restricts that choice. An unknown hash is
a visible error; first log or import a local path in a run rather than inventing
a separate asset service or import command.

A plain file digest says nothing about companion files. A bundle ID is
`sha256-tree` over a canonical inventory of every companion digest; use bundles
for series, meshes, and other multi-file artifacts. Deduplication is exact-byte
identity only; it makes no near-duplicate, block-deduplication, or compression promise.

## Make a lightweight view or comparison

Create an editable workspace referencing the saved sources:

```bash
cherries analysis new exp/2026/10/05/mouthopen/analysis/compare-neutral \
  --source <baseline-id> --source <new-id> --name "Neutral comparison"
```

Write a visualization script, save an application scene, or describe manual
inspection in this folder. Findings go in its `RUN.md` or other authored
documents. Python, ParaView, and the current library environment are available;
a complete replay environment is optional for this workflow. `path` materializes
an artifact's declared companion files too, so a ParaView series comes with its
frames. Save the scene/settings and actual displayed source references when
available.

```bash
cherries analysis save exp/2026/10/05/mouthopen/analysis/compare-neutral \
  --output out/comparison.png --output out/view.pvsm
cherries analysis close exp/2026/10/05/mouthopen/analysis/compare-neutral
```

Save captures the current scripts/procedure, findings, selected artifacts, and
exact source references as a lightweight record. Repeated saves receive new IDs.
Select outputs with repeated `--output` options or `[save].outputs` in
`analysis.toml`; a missing declared output fails save. Drafts in `out/` are not
saved implicitly, and notes-only saves may select no outputs.
The workspace remains editable. Closing releases its workspace hold and local
reader leases; saved analyses retain parent edges and protect their sources.
The saved
computation's own `RUN.md` remains frozen. Use `cherries note <id> --file FILE`
for later observations shown alongside it.

## Review results later

Four distinct controls answer different questions:

| Control | Example | Effect |
| --- | --- | --- |
| Quality review | unreviewed, good, bad, inconclusive | Organizes subjective assessment with findings/history. |
| Free-form labels | promising, baseline, mouthopen | Filters related records; multiple labels are allowed. |
| Important | mark important | Protects logical retention. |
| Keep local | mark keep-local | Preserves this machine's local materialization. |

Execution and scientific validation are displayed alongside these controls.
They are not overwritten by a subjective good/bad judgment.

```bash
cherries browse --quality unreviewed --json
cherries review <id> --quality good --note "Useful fit for the next comparison"
cherries review <id> --quality bad --note "Poor match; execution was valid"
cherries label add <id> mouthopen promising
cherries label remove <id> promising
cherries mark <id> --important
cherries mark <id> --keep-local
cherries browse --quality good --label mouthopen --json
cherries browse --quality bad --json
```

The review queue should show available previews and metrics beside name, ID,
age, kind, execution/validation, review, labels, importance, meeting uses, and
local/remote availability. It loads detailed arrays only when requested.
Review and labels can change later, while their history remains available.
A bad label does not discard data. Unreviewed results remain saved. A good
review does not silently pin a record; use the important control explicitly.

## Record weekly meeting use

A meeting selection is a lightweight analysis of the results actually used:

```bash
cherries analysis new exp/2026/10/05/weekly-meeting \
  --source <run-a> --source <run-b> --name "Weekly meeting selections"
# Save meeting notes in RUN.md and select presented figures/tables.
cherries analysis save exp/2026/10/05/weekly-meeting --used-in weekly/2026-10-05
cherries analysis close exp/2026/10/05/weekly-meeting
cherries browse --used-in weekly/2026-10-05 --json
```

The saved meeting record preserves exact source/artifact references and protects
those runs through parent edges. Its context is searchable from the source run.
An ordinary `used-in-weekly-meeting` label is convenient categorization; the
registered meeting record is the reference that provides retention protection.
A meeting record can omit plots if it only records findings and referenced runs.

## Archive and look back

```bash
cherries archive <id> [<id>...] --remote main
cherries archive <id> --remote main --evict
cherries restore <id>
cherries browse --remote --quality good --label mouthopen --json
cherries browse --remote --asset sha256:<full-digest> --json
cherries show <id> --json
cherries read <id> RUN.md
cherries path <id> outputs/preview.png
cherries sync --remote main
cherries prune --plan
```

Archive uses rclone to upload missing canonical objects, reads them back and
verifies SHA-256, then publishes record manifests/control metadata and its
completion marker last. `--evict` needs that verification plus no local need by
other resident records, active work, reader leases, or this machine's keep-local
flag. Importance protects logical retention, rather than local eviction. It can
free only eligible local bytes because an object may be shared by another record; logical discard never
deletes a blob. Restore pulls missing objects, verifies them, and makes a named
ordinary run view. `path` resolves a manifest into a verified partial view and
retains a reader lease until analysis close or `path --release LEASE`.

Rclone alone provides neither portable atomic same-key publication nor SHA-256
proof. The remote must provide documented atomic immutable publication, or
Cherries must serialize foreground publishers through supported atomic locking
or explicit coordination. Verify the complete object closure; publish the marker
last. Never use a marker-file lock or time-based stale-publisher takeover.

Before publishing a complete marker, validate every parent receipt ID and digest,
reject self-parents/cycles, and resolve pending parents. Unknown or conflicting
parents remain pending and block destructive operations.

Reviews, labels, notes, meeting references, and retention state are preserved
in remote metadata. A fresh machine can fetch a compact metadata checkpoint
and subsequent events, build an index on demand, and query without retaining a
permanent local mirror. If those files were never synced, objects alone cannot
invent the missing history. The CLI reports unknown fields explicitly.

Codex uses `browse` for selection, `show` for provenance and availability,
`read` for findings, and `path` for concrete assets. No persistent browser or
full metadata mirror is required.

## Failure and cleanup presentation

| Situation | Display and behavior |
| --- | --- |
| Successful experiment, value uncertain | Saved; unreviewed. |
| Successful execution, failed scientific validation | Saved; validation failed; awaits manual review/discard. |
| Later review says bad | Still saved; appears in cleanup candidates but has no automatic deletion. |
| Execution exits nonzero or confirmed signal failure | Failure receipt/diagnostics preserved; eligible stopped unsealed local payload discarded. |
| Computation finishes, saving/required output fails | Recording incomplete; retain stage for recovery. |
| Process outcome unknown | Incomplete; establish outcome before retirement. |
| Remote upload/verification interrupted | Archive pending; local data retained. |
| Selected remote object fetched | Partial view; no claim of complete restore or replay. |
| Source has an existing dependent or active workspace hold | Discard unavailable; explain the referencing record/hold. |
| A registered machine cannot join deletion maintenance | Collection-wide discard waits for reconciliation. |

Rare cleanup starts from a preview (`discard <id> --plan`), including dependency,
importance, use, and location information. Logical discard records tombstones
but never deletes canonical blobs. `prune` is a reviewed CAS mark/sweep over all
live records, pending/active holds, and roots. Local GC freezes every
reference-creating path sharing that store; remote GC freezes all reference-creating
operations in the collection namespace and requires every registered machine paused/synced.
An offline machine blocks it. The command never interprets "bad" as permission
to bypass dependencies, importance, or unsynchronized writers.

Closing a browser does not cancel a computation. The Python process and `main` wrapper stay foreground
unless another explicitly selected process owner is implemented; this proposal
does not promise that closing its terminal is safe.

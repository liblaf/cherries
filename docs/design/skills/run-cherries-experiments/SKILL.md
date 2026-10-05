---
name: run-cherries-experiments
description: Historical target design for separate experiment repositories and Cherries sealed-record workflows.
---

# Run Cherries Experiments

## Status and scope

This is a **historical target design**, not the installed skill. The runtime now
implements local CAS sealing, active-run helpers, archive/restore, metadata
merge, labels/reviews, leases, lightweight analysis, `rerun`, payload-free
metadata checkpoints, and single-machine maintenance. Follow the maintained
installed-skill source at `skills/run-cherries-experiments/SKILL.md` and the
[record guide](../../../README.md) for actual commands and limits.

The remaining sections describe intended extensions. Treat automatic environment
reconstruction, remote checkpoint compaction, remote attempt transfer, and
destructive fleet cleanup as unavailable unless the implementation and maintained
skill say otherwise.
The separate experiment repository still owns authored scripts, documents, LFS
fixtures, and Apple/Melon gitlinks; it never owns generated run payloads.

## Repository and storage boundary

Treat these as distinct stores:

```text
experiment-repo/                 # Git superproject
  libs/apple/                    # pinned Git submodule
  libs/melon/                    # pinned Git submodule
  exp/YYYY/mm/dd/study/
    src/  configs/  docs/  fixtures/  analysis/
<configured-storage-root>/       # outside the Git worktree
  objects/sha256/ab/<digest>      # immutable canonical blob
  records/<run-id>/               # record.json, manifest.json, RUN.md
  work/<run-id>/                  # writable independent/reflink copies
  runs/<run-id>/                  # optional ordinary view, never canonical
  metadata/events/<machine-id>/   # durable local updates
  metadata/checkpoints/           # downloaded versioned metadata
  cache/catalog.sqlite            # disposable query projection
  index/
```

Git LFS is only for deliberately curated fixtures and selected reviewable
assets. Generated inputs, logs, checkpoints, and numerical outputs belong in
Cherries CAS storage. Never use broad LFS
patterns that turn every generated mesh or array into a permanent Git object.
Remote storage uses the same objects, records, and metadata layout.
For active library development, the experiment project may use editable path
dependencies to its submodules. This makes current changes visible and makes
capture at active `main` mandatory.
`cherries init --storage PATH` is the planned one-time collection and local
volume registration command. Do not invent it when the installed CLI lacks it.

## Sealed daily experiment

```bash
python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
uv run python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
```

Keep the usual bottom-of-script call; normal arguments remain unchanged:

```python
if __name__ == "__main__":
    cherries.main(main)
```

`main()` runs once in this process. It allocates `work/<id>` on the configured
data volume, captures the entry script, supplied config, runtime evidence, each
relevant repository/submodule HEAD plus combined binary diff, and selected
untracked code copied separately. Work never writable-hardlinks into CAS. The commit bases must remain obtainable. There is no default
bootstrap, relaunch, sandbox, daemon, or complete environment-artifact capture.
This is provenance observed at the `main` boundary, not proof of already
imported module state: record source stability and never claim `replay_verified`.
Keep imports with data reads/writes, GPU or solver setup, hidden random state,
and live config/input parsing inside `main`.
Asset helpers are valid only in active `main`. Config defaults are raw paths or
strings; never call them in class definitions:

```python
class Config(cherries.BaseConfig):
    mesh: str = "sha256:<full-digest>"
def main(cfg: Config) -> None:
    mesh = cherries.input(cfg.mesh, name="mesh.vtu")
    output = cherries.output("solution.npz")
    scratch = cherries.temp("solver")
```

`input` accepts a full `sha256:` digest, local path/source string, or
`run:<id>/path`; it verifies and copies bytes to `work/inputs`. `output` returns
`work/outputs`, `log_output` imports an external result there, and `temp` uses
disposable `work/scratch`.
File content SHA-256 is `asset_id`, canonically stored at
`objects/sha256/<2hex>/<digest>`; manifests/catalog index run, relative path,
digest, and local-or-remote locations. For an unqualified identical asset,
choose a complete local producer then remote, verify it, record chosen
run/path/digests, and register the parent before reading. `source_run=ID`
restricts provenance. Unknown hashes fail visibly; log/import a local path in a
run first. A bundle ID is `sha256-tree` over every canonical companion digest;
plain file hashes do not promise a bundle. Exact equal bytes deduplicate; no
near-duplicate, block-deduplication, or compression promise applies.
On success, import retained work payloads to CAS, stage, fsync, and rename complete
local record metadata, append its sealed event, then reclaim disposable work. Missing
outputs or storage failure yield nonzero `incomplete` and retain the stage.
Execution failures retain a small receipt and discard payload only for a stopped,
unpinned, never-published, unsealed local leaf with no dependent or hold.
Do not automatically create Git commits. An authored experiment or library
commit and outer gitlink update may be made intentionally after inspecting its
scope; it is a convenient reference separate from immutable captured source.

## Lightweight follow-up analysis

Use the planned commands for work that interprets existing records without
claiming strict replay:

```bash
cherries analysis new FOLDER --source ID [--source ID] --name NAME
cherries analysis save FOLDER --output out/figure.png --output out/view.pvsm [--used-in weekly/2026-10-05]
cherries analysis close FOLDER
```

`analysis new` creates an editable study workspace with selected source IDs and
materialized references, then registers a workspace hold on those sources.
Write visualization/comparison scripts and findings in that folder, including
`RUN.md`; use the current development environment, ParaView, or another tool.
For ParaView, obtain complete declared artifact bundles and companions through
`cherries path` or a full `restore`, never a guessed single file. Record the
PVSM/settings and actual displayed artifact references when available.
`analysis save` captures scripts, findings, selected output bytes/references,
and declared source runs as a lightweight dependent record. It does not claim
replayable solver execution, require a clean checkout, or require stamping
casual media. `analysis close` ends the editable workspace without changing
already saved records and releases its workspace hold. Saved analysis edges
remain and protect every source record.
Declare promoted outputs in `[save].outputs` in `analysis.toml`, or repeat
`analysis save --output PATH`. Missing declared outputs fail save.
Use the same workflow for weekly meeting reuse: create a meeting analysis with
every discussed run as `--source`, save its exact references, and optionally
record `--used-in weekly/2026-10-05`. The saved meeting analysis is a dependent
record and protects its sources.

## Archive, restore, and browse

```bash
cherries archive ID [ID ...] [--remote main] [--evict]
cherries restore ID
cherries browse --remote --quality unreviewed --json
cherries browse --remote --label LABEL --json
cherries browse --remote --used-in weekly/2026-10-05 --json
cherries browse --asset sha256:<full-digest> --json
cherries show ID --json
cherries read ID RUN.md
cherries path ID outputs/file
```

Rclone alone is neither atomic same-key publication nor SHA-256 proof. Require a
documented atomic immutable backend or serialized foreground publisher coordination;
never use a marker lock or stale-publisher takeover. Archive uploads and read-back-verifies
the complete closure, then publishes complete manifests/control metadata and marker last. `--evict` needs remote verification
and no local need by other resident records, active work, reader leases, or this
machine's keep-local flag; importance protects logical retention, not eviction.
It frees only eligible bytes because objects may be shared. Restore fetches and
verifies missing objects into a named ordinary run view. `path` materializes the
requested verified artifact plus declared companions, remaining partial. Associate
paths with `--workspace FOLDER`, or release standalone leases with `path --release
LEASE`. Browse/show use the newest digest-valid checkpoint plus later remote and
local unsynchronized events in a disposable cache; no full mirror is required.

Before a complete marker, validate parent receipt IDs/digests, reject self/cycles, and resolve
pending parents; unknown/conflicts remain pending and block destruction.

## Post-hoc review and labels

Every successful experiment starts `quality = unreviewed`. Scientific
validation, execution status, and subjective review are separate fields.

```bash
cherries review ID --quality good --note "Converged and useful for comparison"
cherries label add ID LABEL [LABEL ...]
cherries label remove ID LABEL [LABEL ...]
```

Reviews, notes, labels, and `used-in` associations are append-only metadata
events synchronized remotely. Quality values are `good`, `bad`, `inconclusive`,
or `unreviewed`; they never rewrite sealed records or CAS objects. `bad`
does not auto-discard a successful record; labels alone create no retention policy.

## Retention and deletion

`cherries mark ID --important`, `--no-important`, and `--keep-local` are
planned mutable catalog operations. They do not rewrite immutable record
content or CAS objects.
No record with a dependent may be deleted. This holds for archived records,
important records, copied records, old records, and failed descendants.
Execution failures may have their payload automatically discarded only after the
run is stopped, unpinned, confirmed a leaf, and recorded in deletion history.
Retain validation failures until a user manually discards them.
For shared multi-machine storage, rare deletion requires every registered machine paused
and synchronized, with active readers/leases reconciled. An offline or unknown machine
blocks deletion. Do not replace this with a best-effort local check.
Logical discard retains tombstones and never removes a blob. `prune` marks/sweeps
live records and pending/active holds. Local GC freezes every reference-creating
path sharing that store; remote GC freezes all reference-creating operations in
the collection namespace and requires all registered machines paused/synced.
Offline blocks it.

## Capability gaps and safe reporting

The current in-process `main()` and legacy local plugin do not provide this capture
engine. Eager helpers may run before active `main` (for example in module-scope
configuration) and cannot satisfy passive config defaults or managed asset semantics.
The current default Git profile stages the whole containing repository before
committing; it must not be used by this workflow.
When a proposed command is absent, report the missing implementation and the
smallest next design or implementation task. Do not manually approximate a
sealed run with an unverified copy, invoke automatic Git commits, or delete
records to make the requested workflow appear complete.

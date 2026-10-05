# Cherries records, assets, and storage

Status: proposed breaking redesign, 2026-10-05. The current published runtime
does not implement these staging, CAS, metadata, or remote-storage contracts.
This document supersedes the earlier restic and capture/relaunch proposals.

Run experiments as normal Python scripts. `cherries.main(main)` creates a local
work folder, records source evidence, invokes the callable once in the current
process, then saves the result. All managed inputs/outputs live in that folder.
Canonical storage uses SHA-256 objects and small run manifests. Rclone transfers
objects and metadata on demand. Restic is not part of the core storage design.

## Decisions

| Concern | Contract |
| --- | --- |
| Run UX | `python src/10-run.py --steps 200`, with the usual `cherries.main(main)` call. |
| Work folder | `work/<UUID>/` on a configured local data volume, never system `/tmp`. |
| Input | Copy verified bytes into the run before returning a path to computation. |
| Output | Write under the active work folder; retain only declared/logged artifacts. |
| Source evidence | Entry script plus commit ID and binary patch per involved repository; selected untracked code copied separately. |
| Storage | Immutable content-addressed objects; record manifests map ordinary logical paths to objects. |
| Review | Successful records start unreviewed; quality, labels, importance, and meeting uses are added later. |
| Archive | Upload missing CAS objects and small records with rclone; verify before local eviction. |
| Retention | Existing dependents block logical deletion; shared objects are reclaimed separately by reachability. |

`experiment` records staged data and source/runtime evidence around ordinary
execution. `analysis` records selected scripts/procedures, findings, outputs,
and exact source references with a lightweight guarantee. Neither exit zero nor
a saved manifest claims scientific validity, bitwise replay, or isolation.
Breaking changes simplify the contract; no compatibility layer for module-scope
live path helpers is required.

## Experiment repository

Use a separate Git/LFS superproject. Apple and Melon remain library repositories:

```text
experiments/
  pyproject.toml  uv.lock  cherries.toml
  .gitmodules  .gitattributes  .gitignore
  cherries.local.toml                # ignored machine-specific volume settings
  libs/apple/                       # submodule
  libs/melon/                       # submodule
  tools/                            # shared authored experiment helpers
  exp/2026/10/05/mouthopen/
    src/10-run.py
    configs/baseline.toml
    fixtures/                       # curated inputs, optionally LFS
    docs/README.md
    experiment.toml                 # optional study defaults
    analysis/compare-neutral/
      analysis.toml  src/10-compare.py  RUN.md
      out/                          # ignored drafts; explicit output promotion
    published/                      # deliberately curated figures/tables
```

Git owns authored scripts/config/locks/reports and optional small receipts. LFS
owns curated fixtures and selected published assets, using path-scoped rules.
Bulk run inputs/outputs, logs, scratch, and canonical objects stay outside Git.
Resolve LFS pointers before importing inputs. Do not move experiment files into
library repositories. [Git LFS](https://git-lfs.com/)

A normal uv project can use editable submodule path dependencies:

```toml
[project]
name = "research-experiments"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["liblaf-apple", "liblaf-melon", "liblaf-cherries"]

[tool.uv.sources]
liblaf-apple = { path = "libs/apple", editable = true }
liblaf-melon = { path = "libs/melon", editable = true }
```

Commit `uv.lock`. Capture each involved submodule's own Git evidence; the
superproject's gitlink does not contain dirty child source. Record Python,
installed packages, lock/build declarations, seeds, and relevant device/driver
constraints. No fresh environment or complete dependency-artifact copy is
required per run. Later replay needs obtainable Git commits/packages and a
compatible runtime. [uv path dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/#path)

## Local and remote stores

`cherries init --storage /home/liblaf/Data/cherries/research` creates or enrolls
a collection and registers its local volume. This path is an example, not a
directory created by the proposal. Default: `~/.local/share/cherries/collections/<id>/`.
Work, local object publication, and record publication use appropriate
same-filesystem staging for atomic renames.

```text
<storage-root>/
  collection.json
  work/<run-id>/                    # writable, independent experiment copies
  objects/
    sha256/<first-2-hex>/<digest>     # immutable raw file blobs
    sha256-tree/<first-2-hex>/<digest> # canonical bundle/tree manifests
  records/<run-id>/                  # small authoritative record metadata
    record.json  manifest.json  RUN.md  complete.json
  runs/<run-id>/                     # optional named materialized view
  metadata/
    events/<machine-id>/<event-id>.json
    checkpoints/<checkpoint-id>/
  cache/catalog.sqlite              # disposable query/hash-location projection
  cache/selected/                   # verified partial materializations
  index/                            # generated summaries/galleries
```

```text
<remote-prefix>/<collection-id>/
  objects/sha256/...
  objects/sha256-tree/...
  records/<run-id>/record.json
  records/<run-id>/manifest.json
  records/<run-id>/RUN.md
  records/<run-id>/complete.json
  metadata/events/...
  metadata/checkpoints/...
```

Example settings, with credentials outside records:

```toml
# cherries.toml
[collection]
id = "<collection-uuid>"

[capture]
roots = ["libs/apple", "libs/melon", "tools"]

[execution]
failure_payload = "discard"

[archive.main]
path = "archive:cherries/<collection-uuid>"
publication = "serialized"
```

```toml
# cherries.local.toml, Git ignored
[collection]
storage = "/home/liblaf/Data/cherries/research"
```

Canonical objects are shared storage. Active work and materialized views are
independent copies/reflinks, so they may consume extra space. Never use writable
hardlinks/symlinks into immutable objects. A saved record need not retain a full
materialized view; `path`/`restore` reconstruct familiar filenames on demand.
A portable standalone export materializes its complete file tree explicitly.

## Simple Python API

Keep normal imports, configs, functions, and the bottom main guard. Config
defaults hold source paths or asset IDs; artifact helpers require an active run
and are called inside `main`. Calls outside it fail clearly.

```python
from pathlib import Path

from liblaf import cherries


class Config(cherries.BaseConfig):
    mesh: str = "sha256:<full-file-digest>"
    steps: int = 100
    seed: int = 0


def main(cfg: Config) -> None:
    mesh: Path = cherries.input(cfg.mesh, name="mesh.vtu")
    output: Path = cherries.output("solution.npz")
    # Read mesh, compute, and write output.
    cherries.log_metrics({"loss": 0.1})


if __name__ == "__main__":
    cherries.main(main)
```

```bash
python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
uv run python exp/2026/10/05/mouthopen/src/10-run.py --steps 200
```

The optional study file supplies name/labels/config defaults, not a required
launcher language. Script argv, cwd, imports, and Ctrl-C stay normal. BaseConfig
parses scalar/source arguments once after run/log setup; custom parsers may log
resolved parameters through `log_params()`. No bootstrap, self-relaunch,
sandbox, or persistent service is required.

| API | New behavior |
| --- | --- |
| `main(fn)` | Allocate a run, capture evidence, instantiate/log config, invoke once, finalize. |
| `input(SOURCE, name=..., source_run=...)` | Resolve path/hash/run reference, copy and verify into `work/<id>/inputs/`, return its Path. |
| `output(NAME)` | Return `work/<id>/outputs/NAME`; require the file at successful finalization. |
| `temp(NAME)` | Return `work/<id>/scratch/NAME`; disposable unless promoted. |
| `log_output(PATH, name=...)` | Import an external result into outputs, or register an already managed result. |
| `log_asset(PATH, name=...)` | Retain another explicit artifact under `artifacts/`. |
| `log_metric(s)`, `set_step()`, `log_params()` | Persist run-local metric/parameter streams and normal logs. |
| `open_run(ID, workspace=...)` | Closeable analysis accessor for verified paths plus logical/read-residency holds. |

Names are run-relative; reject absolute/`..` escapes and conflicting destinations.
Compute with the Path returned by `input`, never the original mutable source.
Compare copied source/target bytes and required companions. Output names are
independent between runs, including concurrent processes. Raw source declarations
and actual staged bindings are recorded separately with relocatable paths.

Inside work, the familiar layout is:

```text
work/<run-id>/
  inputs/  outputs/  artifacts/  scratch/  logs/
  source/entrypoint.py
  source/git/project/{commit.json,working-tree.patch,status,untracked/}
  source/git/libs/apple/...
  source/git/libs/melon/...
  config/{resolved.json,bindings.json}
  environment/{pyproject.toml,uv.lock,runtime.json}
```

## Source evidence

At the main boundary, copy the entry script and record each involved Git repo's
relative path, HEAD commit ID, status, recursive submodule topology, and tracked
working-tree patch. One patch can represent staged and unstaged final content:

```bash
git diff --binary --full-index --no-ext-diff --no-textconv \
  --ignore-submodules=dirty HEAD
```

The parent patch preserves changed gitlink commits without an unapplyable dirty
suffix; independently capture every relevant child repo. This recipe was checked
in a disposable parent/submodule repository with staged/unstaged text and binary
changes and a dirty child. Reconstructed file bytes matched.
The combined patch does not preserve the original index/worktree split; separate
staged/unstaged patches are needed only if that distinction matters.
[Git diff](https://git-scm.com/docs/git-diff)

Untracked files are absent from Git diff. Copy selected required untracked code
with paths/hashes; explicitly include required ignored build/source inputs.
Do not capture environments/caches indiscriminately. A new untracked entrypoint
is retained directly. The runner never does `git add --all` or creates commits.
[Git file inventory](https://git-scm.com/docs/git-ls-files)

Reconstruction uses an independent checkout of the recorded base commit,
verified patches and copied untracked files, separately for each submodule.
Referenced commits, including unpushed child commits, must remain obtainable;
a SHA/patch is not an offline copy of the base Git objects. A missing HEAD or
non-Git source requires an explicitly selected source copy. Report unavailable
bases instead of pretending replay succeeded.
[Git patch application](https://git-scm.com/docs/git-apply)

Compare source evidence before/after execution and report source stability.
Capture begins after top-level imports, so it cannot prove what an already-loaded
module imported earlier. Keep data loading, experiment writes, GPU/solver setup,
and run-dependent state inside `main`. `recorded`, `source_stability`, scientific
validation, and `replay_verified` are separate. Changed source is reported and
retained for inspection rather than silently called a verified replay.

## Asset identity, bundles, and provenance

A file ID is `sha256:<64 hexadecimal digits>` over raw bytes. Normalize spelling
and retain the full digest. Identical bytes have one content ID regardless of
filename or producing run. New outputs receive IDs when retained bytes are
finalized; changing them creates different content. Modes, roles, descriptions,
and scientific context are manifest metadata rather than file-byte identity.
[Python SHA-256](https://docs.python.org/3/library/hashlib.html)

```python
mesh = cherries.input("sha256:<full-file-digest>", name="mesh.vtu")
mesh = cherries.input(
    "sha256:<full-file-digest>", name="selected.vtu", source_run="<producer-id>"
)
# A local source can introduce an asset into a saved run:
fixture = cherries.input("fixtures/face.vtu", name="fixture.vtu")
```

Hash lookup uses an index built from published record manifests:
`asset_id -> [(run_id, logical_path, record_digest, location)]`. Prefer a complete
local occurrence, then a verified selected copy, then registered remote storage;
break ties by stable run/path ordering. Record the selected origin visibly.
`source_run=` or `run:<id>/outputs/path` restricts context when the producing run
matters. Same bytes do not imply the same scientific provenance.

Before reading a selected record asset, register its producer run as a parent
and obtain any local reader lease. The binding contains producer UUID,
record/manifest digests, logical path, asset ID/size, and verified location.
Only the chosen origin gets a dependency edge. A candidate retired/conflicting
during lookup is rejected before exposure. Unknown hashes fail clearly; a hash
does not encode its physical address or trigger a scan of unrelated disks.
Import a local source through a run first, or connect/sync the collection that
contains the published asset.

For multi-file artifacts use `sha256-tree:<digest>` over a deterministic,
versioned tree manifest. Entries contain canonical relative POSIX paths, kinds,
file IDs, sizes and retained executable flags; names/entries are sorted using
the schema's fixed byte ordering, not locale or traversal order. Canonical UTF-8
encoding and a tree-domain/version prefix determine the hash; do not normalize
Unicode or depend on pretty JSON formatting. Reject escaping links and unresolved
LFS pointers; declared link targets are materialized as ordinary files.
All required companions are covered. A `.series` file's SHA-256 alone does not
identify its VTK frames. File-hash input copies that file; tree-hash input copies
the verified complete bundle preserving its relative topology.

## CAS records and finalization

Each complete record maps logical filenames to immutable objects. Example
manifest fragment (the displayed digest is abbreviated only for explanation):

```json
{
  "schema": "cherries-manifest-v1",
  "files": [
    {"path": "inputs/mesh.vtu", "asset_id": "sha256:FULL_DIGEST", "size": 1234},
    {"path": "outputs/solution.npz", "asset_id": "sha256:FULL_DIGEST", "size": 5678}
  ]
}
```

The record contains parameters, input origins, parents, execution/validation,
source evidence references and manifest digest. `RUN.md` is a small readable
summary. Small control files may be inline; bulk payload bytes live once in CAS.
The complete marker binds schema, UUID, record/manifest/root/closure digests and
publication metadata. Keep object, tree, record, and commit hash domains defined
by schema. Readers accept only complete, digest-valid records.

On normal return from `main`, stop/join output writers, flush and close logs,
validate required artifacts, and hash retained work files. Persist a publication
intent protecting the object closure. For each new object, write a same-filesystem
temp file, hash/verify it, fsync, then atomically publish its digest path. Verify
any preexisting object rather than trusting a filename. Never edit published
objects. Write and fsync record/manifest/complete metadata in a same-filesystem
staging directory, then atomically rename it into `records/<id>/` and fsync the
parent directory. Persist the sealed event afterwards. Only then may disposable
work be reclaimed.
A user requesting a local view gets independent copies/reflinks in `runs/<id>/`.

An interrupted ingest yields pending/protected objects, not a successful run.
Recovery reconciles intents/markers and only then releases abandoned roots.
Missing output or required recording failure returns nonzero and preserves work
as incomplete. Optional Comet reporting cannot bypass or invalidate required
local evidence persistence. Successfully saved experiments start unreviewed.

Whole-file CAS deduplicates exact bytes. Repeated fixtures or identical outputs
share an object even across runs/machines. Different files, including similar
meshes or arrays, remain distinct. Compression, chunk deduplication, packing,
and always retaining materialized views are not part of this minimal design.
Hashes/names can stay stable across local/remote tiers; CAS is not automatically
an encryption layer. No restic deduplication is needed for these space savings.

## Failure, validation, and repeat

A nonzero exception/confirmed signal is execution failure. Persist bounded
diagnostics and its outcome before removing eligible bulky work. Auto-discard is
allowed only for the owning machine's stopped, unpinned, never-published unsealed
attempt, with no child/hold; retain a small failure/tombstone event. Never delete
shared CAS objects as part of removing work. Newly unrooted objects are later
GC candidates. If the attempt has dependents or uncertain ownership, retain it.
A recording-incomplete or unknown interrupted attempt stays for recovery.

A successful execution with failed scientific validation is saved and discarded
only manually. A bad quality review also leaves it saved. Keep validation results
separate from execution exceptions.

`rerun ID` reconstructs source from Git evidence, resolves compatible environment
recipe and saved input content IDs, then executes the script with a new UUID.
It does not reread the old source path or overwrite the old record. The new run
references the original and selected asset origins. Report unavailable commits,
packages, runtimes, or bytes. Comparing declared tolerances is distinct from
scientific validation. Resume needs an experiment-specific checkpoint protocol.

## Lightweight analysis and meeting use

```bash
cherries analysis new exp/2026/10/05/mouthopen/analysis/compare-neutral \
  --source <run-a> --source <run-b> --name "Neutral comparison"
cherries analysis save exp/2026/10/05/mouthopen/analysis/compare-neutral \
  --output out/comparison.png --output out/view.pvsm
cherries analysis close exp/2026/10/05/mouthopen/analysis/compare-neutral
```

`new` creates an editable folder and registers source holds. Use ordinary Python,
ParaView, and current library tools; findings go in workspace `RUN.md`. Source
changes use `analysis source FOLDER --add ID/--remove ID` before consumption.
`save` publishes a new lightweight CAS-backed record containing current scripts
or procedure, findings, selected outputs and exact source refs. Every save has a
new UUID. No clean checkout, full environment capture, or mandatory media stamp.

Select outputs with repeated `--output` or `[save].outputs` in `analysis.toml`.
Missing selected files fail save; ignored drafts are not silently retained.
Workspace `out/...` becomes logical `outputs/...` preserving topology. Notes-only
saves may select no outputs. Materialize complete bundles for external viewers;
save PVSM/settings and actual displayed sources when available.

Managed access holds logical sources and local residency leases. Closing a
workspace/accessor releases owned temporary holds; saved parent edges remain.
Rebinding a viewer to an independent cache may release an old replica's residency
lease, while its logical read hold persists until the viewer finishes. Unmanaged
external paths need explicit keep-local if residency is required.
Later findings can also use `note ID --file FILE`; the record's saved summary
remains frozen.

```bash
cherries analysis new exp/2026/10/05/weekly-meeting \
  --source <run-a> --source <run-b> --name "Weekly meeting selections"
cherries analysis save exp/2026/10/05/weekly-meeting --used-in weekly/2026-10-05
cherries analysis close exp/2026/10/05/weekly-meeting
```

Meeting records preserve presented selections/findings and protect their exact
source runs. The used-in context is searchable on those runs and survives tier
changes. Correcting a saved meeting creates a new revision. An ordinary label
`used-in-weekly-meeting` categorizes; the registered reference provides retention
protection.

## Post-hoc review

| Facet | Values/effect |
| --- | --- |
| Execution/validation | Evidence of success/failure and scientific passed/failed/unknown. |
| Quality | unreviewed, good, bad, inconclusive; revisable judgment with author/time/note/history. |
| Labels | Free-form multiple categories such as baseline, promising, mouthopen. |
| Important | Collection-wide logical retention protection. |
| Keep local | This machine's residency preference. |
| Used in | Registered meeting/analysis context and exact source refs. |

```bash
cherries browse --quality unreviewed --json
cherries review <id> --quality good --note "Useful fit for comparison"
cherries label add <id> mouthopen promising
cherries mark <id> --important
cherries mark <id> --keep-local
cherries browse --used-in weekly/2026-10-05 --json
cherries browse --asset sha256:<digest> --json
```

Good does not automatically pin; bad, age, and unreviewed do not automatically
delete. Successful records remain saved until explicit retention action.
The review queue shows previews/metrics, IDs/names, quality, validation, labels,
importance, meeting uses, parents, asset IDs and local/remote availability.
Reviews/labels/notes/flags are small external append-only events; updating them
does not rewrite run manifests or numerical blobs.

## Archive, restore, and browse

`archive ID... --remote main` computes each record's transitive object closure,
uploads missing objects with rclone, verifies remote bytes, then publishes the
small record/manifest/control metadata and a read-back-verified complete marker
last. That marker binds run/root/closure digests and the metadata events/prefixes
establishing origin, location and retention state. Incomplete uploads are pending;
no complete record marker means no archived run and no basis for local eviction.

Rclone's copy skip logic and `--ignore-existing` are not SHA-256 verification.
A filename/size/mtime/provider checksum is not enough. Read remote bytes and
compute the required SHA-256; every object entering a verified archive closure
needs that proof, including existing objects. A supported immutable/versioned
backend may reuse explicitly documented, still-valid verification evidence.
Otherwise perform full read-back before claiming archive verification.
Use copy-style immutable publication, never generic `sync`, `move`, or cleanup
of this namespace. [rclone copy](https://rclone.org/commands/rclone_copy/)

Rclone does not supply a portable atomic create-if-absent lock across all
backends. The configured remote must provide documented atomic immutable object
publication, or Cherries must serialize collection publication using a supported
atomic lock or explicit coordination of registered publishers. The default
`serialized` setting is a required operational boundary, not a lock implemented
by writing a rclone marker. No time-based automatic takeover of uncertain
publishers. Readers trust verified markers and validate requested object bytes.
Remote publication and GC cannot race. This is foreground coordination, not a
permanent background service.

`--evict` releases only eligible local views/objects after verified remote
closure availability. Keep every object needed by other unarchived/resident local
records, this machine's keep-local roots, active work, pending transactions, or
reader leases. A shared object may free no space when another local record still
needs it. Importance protects logical retention, not mandatory local residency;
saved dependents permit verified local eviction but still block logical deletion.

`restore ID` downloads missing verified objects and materializes the logical file
tree under `runs/<id>/`. `path ID RELPATH` resolves and verifies a selected file
or declared bundle into a cache/view; it remains explicitly partial. The hash
alone does not supply companions. Same-ID/different-record-digest fails visibly.
A standalone reader lease ends with `path --release LEASE`; a workspace owns its
leases until close/rebind. Replay may still need Git bases/environment resources.

Codex uses `browse`, `show`, `read`, and `path`. Remote records retain readable
summaries/manifests; metadata checkpoints enable search without downloading all
payloads. A fresh machine can build an ephemeral projection from a valid complete
checkpoint plus uncovered remote/local events, or individual published records.
No persistent complete local metadata mirror, mount, CAS daemon, or web server is
required. An optional generated gallery/index is disposable. Missing control
history is reported unknown; payload hashes cannot invent it.

## Multi-machine merge, retention, and garbage collection

Normal operations append unique records and per-machine events. Same UUID/digest
means replicas; same UUID/different digest is an error. Same file digest means
shared content, not a parent edge by itself. A machine can record locally while
offline, including durable local parent registrations; later metadata merge
unions records/events and content-location evidence.

Validate parent receipt IDs/digests for every new edge at publication/import.
Reject self-parent edges and cycles. Resolve explicitly declared pending parents
before publishing a complete record; missing/conflicting parent receipts leave
the registration pending and block destructive maintenance. Retained historical
edges are not new active references.

Remote events/checkpoints preserve parent edges, asset origins, location proofs,
reviews, notes, important/keep-local flags, workspace/export/read holds, failures,
tombstones and pending intents. Local unuploaded records/events are durable;
downloaded checkpoints/query indexes are disposable. Checkpoints name machine
prefix coverage and digests, with a verified complete marker last. Timestamp
alone does not establish completeness; merge uncovered remote and local events.

Concurrent quality judgments remain visible. Label/pin removals clear only
positive events the writer observed; unseen/concurrent positive pins survive.
Workspace/read/export releases name owned holds. Keep-local events are keyed by
(run UUID, machine UUID); A cannot clear B's preference, nor does B's preference
block A's verified local eviction. Enrollment/retirement is coordinated; freeze
membership during collection maintenance.

No record with any existing dependent may be deleted, including analyses,
meeting records, active workspaces, and archived/offline children. Importance,
active read/export holds, and uncertain ownership also block logical discard.
No implicit cascade, backup exception, age override, or force bypass.

For logical discard and remote GC, every registered machine must pause new
parent-consuming/publication operations, reconcile workers/holds/reader leases
and pending object/record intents, synchronize its prefixes and root inventory,
and join a maintenance receipt naming exact participants. An offline/unknown
writer or incomplete graph/root inventory blocks destructive maintenance.
Apply only a reviewed plan, recheck within that frozen boundary, write a durable
tombstone, retire all registered copies/commits, then release the deleted child's
outgoing active parent edges. Keep historical provenance.

Logical retirement does not immediately delete object files. `prune` is a
separate reviewed mark-and-sweep over all live records and transitive tree/file
refs, active work/read/export/keep-local roots, unretired failure receipts,
and pending transactions. Tombstoned record payloads cease to be roots only
after completed retirement; the small tombstone/history is retained. Never delete
objects by listing one discarded run's files: other runs may share them.
Unknown references, incomplete inventories, or missing control metadata block
sweep. Freeze all reference-creating operations across the whole collection's
remote CAS namespace during remote mark/recheck/sweep. Local CAS GC likewise
freezes every local work/ingest/publication path sharing that object store. A
per-run pause is insufficient: another record can reference the same digest.
Local cache eviction is separate from destroying the last referenced copy.

Stopped unsealed failed attempts have the narrow local cleanup exception already
stated. Retire their pending/outgoing edges only after failure history is durable;
shared or externally published objects still obey the normal root/GC boundary.
Batch garbage collection when reclaiming space is worthwhile; daily recording
is primarily append-only.

## CLI and Codex skill

| Command | Result |
| --- | --- |
| `init --storage PATH` | Configure collection, machine and local volume. |
| `python SCRIPT [ARGS...]` | Normal run through its main wrapper. |
| `rerun ID` | Reconstruct recorded evidence and create a new run. |
| `analysis new/save/close`, `analysis source` | Manage lightweight authored work, promoted outputs and exact references. |
| `browse [--remote] [--json]` | Search quality/labels/used-in/asset IDs and availability. |
| `show ID --json`, `read ID RELPATH` | Inspect receipt, annotations, manifest and selected text. |
| `path ID RELPATH [--workspace FOLDER]`, `path --release LEASE` | Materialize selected verified assets and manage reader leases. |
| `archive ID... [--remote main] [--evict]` | Publish verified CAS closures/records, optionally release eligible local bytes. |
| `restore ID` | Verify objects and create a complete named local view. |
| `review ID --quality VALUE [--note TEXT]` | Append a revisable quality judgment. |
| `label add/remove ID LABEL...` | Change free-form categories. |
| `mark ID --important/--no-important`, `--keep-local/--no-keep-local` | Logical protection versus per-machine residency. |
| `note ID --file FILE`, `link ID --git COMMIT` | Add findings or optional authored commit reference. |
| `sync [--remote main]`, `index rebuild [--remote]` | Merge metadata and rebuild query/hash-location projections. |
| `maintenance pause/resume` | Participate in coordinated collection maintenance. |
| `discard ID --plan`, `discard --apply PLAN` | Review and retire eligible leaf records. |
| `prune --plan`, `prune --apply PLAN` | Review and reclaim unreachable CAS objects. |

Machine JSON uses full IDs and one result on stdout; logs/progress use stderr.
Human UUID abbreviations must be unique; asset IDs in manifests remain complete.
Distinguish complete materialized view, locally available object closure,
remote-only, partial, pending/incomplete, and retired; none implies validation.

The [Codex skill draft](skills/run-cherries-experiments/SKILL.md) encodes this
workflow and first checks installed capabilities. It must not approximate a new
record with legacy live-path snapshots or automatic Git commits. The breaking
release may deliver these contracts together; incremental compatibility is not
required. The installed skill/runtime are unchanged by this design artifact.

Acceptance cases include independent concurrent work folders, helper-outside-main
refusal, file/hash/tree inputs, recorded provenance selection, same bytes/shared
objects, missing companions and hash mismatch, dirty binary/submodule/untracked
Git reconstruction, unavailable Git bases, source changes during execution,
missing output/save failure, interrupted CAS ingestion/publication, failed versus
validation-failed experiments, post-hoc labels/meeting protection, shared-object
local eviction, fresh-machine metadata lookup, publisher concurrency boundary,
offline-writer GC refusal and reachability-safe leaf retirement.

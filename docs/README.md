# Cherries project/run stores

Cherries stores experiments and visualizations as UUID run folders with shared
content-addressed data, YAML metadata, Parquet metrics, direct reports and
self-contained source archives. Linux and Python 3.12 or newer are required.

The [root README](../README.md) contains installation, configuration and a
complete first-run example. The detailed [storage workflow](design/storage-workflow.md)
and [CLI/API contract](design/storage-cli-api.md) specify file roles and lifecycle.

## Workflow

1. Initialize one store and register each Git project.
2. Edit code/configuration in the source repository.
3. Record with `cherries.run(...)` or `cherries run exec -- COMMAND`.
4. Inspect reports directly; obtain pointer-backed data through File APIs.
5. Add explanations, assets and tags to the same saved run.
6. Create a new run for each new computation or visualization and pin source files.
7. Copy selected runs and source closure into an initialized archive store.
8. Check target receipts, delete eligible local records, then collect unreferenced CAS.

```bash
cherries store init /data/cherries
cherries --store /data/cherries project add my-project --repo .
cherries run exec --name baseline -- uv run python experiment.py
cherries run list --refresh
cherries run validate <run-id>
cherries file path <run-id> outputs/result.vtu
cherries metrics export <run-id> --to metrics.csv
cherries index rebuild
cherries store verify --objects
cherries store recover
```

Select `[project].id` in `cherries.toml` and `[store].path` in
`cherries.local.toml`, or use `--project` and `--store`. Global options can appear
at command depth; arguments after `--` belong to the child unchanged.
`--json` emits a versioned envelope; diagnostics go to stderr.

## Source selection

Source capture uses private Git indexes and creates fixed `refs/runs/<id>`
without changing the developer's HEAD/index. The archive includes reachable
Git objects and LFS contents, recursive submodules and explicitly configured
external dependencies. Include/exclude paths are relative to each source repo.

```toml
[source]
exclude = ["generated", "downloads"]

[source.dependencies]
solver = "../solver"
```

External Git dependencies restore below `external/<name>`; rebuilding an
execution environment and installing these sources are separate actions.
Source stability compares observed boundaries; replay is not automatically verified.

## Failures and durability

`on_error = "keep"` retains diagnostic failed runs by default. Missing required
outputs on success or changed consumed inputs prevent publication. An interrupted
or failed save preserves `.tmp` and available metric evidence. Recovery does not
restart scientific computation or delete old work implicitly.

Metric calls default to `metric_durability = "fsync"`; choose `flush` explicitly
for immediate visibility without per-call durability confirmation. JSONL uses
`name, step, timestamp_ms, value`, preserves repeated rows, and encodes NaN and
infinities explicitly before conversion into Float64 Parquet values.

`RunResult` distinguishes execution outcome, publication and confirmed save.
An unconfirmed post-rename directory sync reports `published=true, saved=false`;
cleanup/index errors after confirmed save are warnings.

## Editing, copying and deletion

API/CLI edits publish only changed files through recoverable transactions.
Consumed inputs and execution evidence are fixed. Manual report/YAML edits need
`run validate` and `index refresh`. Ordinary edits replace current descriptions;
whole-run historical revisions are not provided.

`run copy` preflights source closure and target identities. Same UUID with
different execution evidence is rejected. Mutable differences require explicit
`--replace --expect <target-fingerprint>`; no timestamp-based overwrite occurs.
`run export --with-data` exports data and reports but is not a source archive.

Deletion is blocked by retained source dependents. GC scans all project references,
protects active work and declared preservation roots, and refuses unknown material
or unfinished transactions. Git/LFS is maintained separately from global CAS.

## Previous stores

The [v4 collection documentation](legacy-records.md) remains available. Explicit
v4 configurations and profiles keep their recorder, and `cherries legacy ...`
exposes old commands. The new Store API rejects old collection paths.

`run import SOURCE --inspect` recognizes sealed collections and migrated run
folders without initializing or cleaning the source. `run import SOURCE` verifies
payloads, preserves IDs and original controls under `legacy/`, and marks source
provenance incomplete. It does not infer a code archive from patches or claim replay.

No production collection, migrated NAS folder or running scientific experiment is
modified merely by upgrading the package.

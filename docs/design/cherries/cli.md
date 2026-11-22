# Cherries CLI

Command-line interface matching the [storage design](storage.md).

## Synopsis

```text
cherries [--repo REPO] [--project-id ID] [--remote RESTIC_REPO] COMMAND ...
```

Global options come before `COMMAND`. Without `--remote`, commands operate on
`<git-root>/cherries/`. `--remote` accepts any Restic repository path or URL
(such as `/mnt/archive/cherries`, `sftp:nas:/archive/cherries`, or `s3:...`).
Exit code `0` indicates success; errors print to stderr with a non-zero exit.

## Query and Locate

```text
cherries list [--tag TAG]... [--param KEY=JSON]... [--search TEXT]
  [--limit N] [--unfinished] [--json]
cherries show RUN [--json]
cherries path RUN
```

- `list`: lists completed runs newest-first by UUIDv7 (local or `--remote`).
  `--unfinished` lists local `.tmp` records. Filters combine with logical AND;
  `--search` matches substrings of `run-name` and `description`; `--param`
  checks top-level JSON equality.
- `show`: prints `run.yaml` (or JSON with `--json`; local or `--remote`).
- `path`: local only; prints the absolute run directory path for direct shell
  access:

```bash
ls "$(cherries path "$RUN")/outputs"
cp "$(cherries path "$RUN")/outputs/result.vtu" ./result.vtu
```

## Annotate and Add Reports (Local Only)

```text
cherries edit RUN [--name TEXT] [--description TEXT | --clear-description]
  [--add-tag TAG]... [--remove-tag TAG]...
  [--metadata KEY=JSON]... [--unset-metadata KEY]...
cherries add RUN SOURCE --as TARGET
```

Restic snapshots are immutable, so `edit` and `add` operate only on completed
local runs; re-push after editing.

`add` copies a file or directory into `figs/`, `assets/`, `reports/`,
`README.md`, or `README.html`. Adding under `figs/` validates and updates
`run.yaml.artifacts.figs`.

```bash
cherries edit "$RUN" --description "Result verified" --add-tag selected
cherries add "$RUN" figs/loss.png --as figs/loss.png
cherries add "$RUN" figs/loss.png --as assets/loss.png
cherries add "$RUN" analysis.md --as README.md
```

## Artifact Lineage and Pruning

```text
cherries lineage [RUN ...] [--tag TAG]... [--json]
cherries prune [RUN ...] [--tag TAG]... [--unfinished] [--dry-run] [--json]
```

Works locally and with `--remote`. Seeds come from explicit `RUN` arguments
and/or `--tag` filters:

- `lineage`: prints the transitive upstream runs required by the seeds.
- `prune`: keeps the lineage closure and removes all other completed runs
  (refusing if zero runs match the seed selection; plus `.tmp` runs locally
  with `--unfinished`; on `--remote`, runs a single `restic forget --prune`).
  Pass `--dry-run` to preview `keep` and `remove`.

## Restic Archive, Restore, and GC

```text
cherries --remote RESTIC_REPO push RUN
cherries --remote RESTIC_REPO pull RUN [--overwrite]
cherries --remote RESTIC_REPO gc [--dry-run]
```

- `push`: archives a completed local run as one Restic snapshot tagged
  `cherries,project:<project-id>,run:<UUIDv7>`, auto-initializing a missing
  repository and skipping unchanged re-pushes. Prints the snapshot ID.
- `pull`: restores a remote run into its original `start-time` date partition
  under `<git-root>/cherries/runs/YYYY/mm/dd/<UUIDv7>/`, verifying staged files
  before replacing an existing copy (`--overwrite`).
- `gc`: keeps only the latest snapshot per run (`--keep-last 1`) and prunes
  unreferenced packs (scoped to `--project-id` if explicitly passed).

## Delete and Verify

```text
cherries remove RUN
cherries verify RUN
```

- `remove`: locally deletes the run directory and empty date parents; with
  `--remote`, forgets all snapshots for that run in Restic.
- `verify`: local only; verifies `run.yaml`, date partition, `run.log`,
  `metrics.parquet` schema, entry script in `src/`, and SHA-256/size of all
  registered artifacts. To verify a remote Restic repository, run
  `restic -r RESTIC_REPO check`.

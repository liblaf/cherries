# Storage and Workflow

See also the [CLI reference](cli.md), [example script](example.py), and
[Python API reference](../../reference/liblaf/cherries/README.md).

## Repository Layout

```text
<git-root>/                         # default project-id is this folder name
├── .git/                           # normal dev history (never mutated by Cherries)
├── .gitignore                      # ignores cherries/ and study data/, figs/, tmp/
├── pyproject.toml / uv.lock        # external libraries pinned via uv.lock
├── exp/YYYY/mm/dd/<study>/
│   ├── README.md                   # study overview and links to runs
│   ├── src/10-run.py               # experiment entry script
│   ├── data/                       # working inputs and outputs
│   ├── figs/                       # working figures
│   └── tmp/                        # debug intermediates; never collected
└── cherries/                       # local run records, ignored by Git
```

## Local Runs and Restic Archives

```text
<git-root>/cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/

<restic-repo>/                      # local mount, SFTP, S3, rclone, etc.
  └─ snapshot(tags=["cherries", "project:<project-id>", "run:<UUIDv7>"])
```

- Local runs are ordinary directories with real files copied via Linux reflinks
  when available (falling back to regular copy; no symlinks or hardlinks).
  Every local run directory is completely self-contained.
- The `YYYY/mm/dd` partition comes strictly from the persisted `run.yaml`
  `start-time` in its original local timezone. Finishing after midnight or
  pushing/pulling across timezones keeps that partition.
- Active or failed runs keep a `.tmp` suffix; completed runs drop `.tmp`
  atomically. `remove` prunes empty date directories up to `cherries/`.
- Remote archiving delegates deduplication, locking, integrity checks and
  garbage collection to [Restic](https://restic.net/). `push` runs
  `restic backup .` from inside the run directory so snapshot roots directly
  contain `/run.yaml`, `/outputs/...`, and `/src/...`, with immutable tags
  `cherries`, `project:<project-id>`, and `run:<UUIDv7>`, `--host cherries`,
  `--group-by tags`, and `--skip-if-unchanged`.
- When none of `RESTIC_PASSWORD`, `RESTIC_PASSWORD_FILE`, or
  `RESTIC_PASSWORD_COMMAND` is set, Cherries passes `--insecure-no-password`.
  `push` runs `restic init` automatically if the repository does not exist yet.

Each run directory contains the following files (created on demand):

| Path                                    | Contents                                                | After completion                                       |
| --------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------ |
| `run.yaml`                              | Run metadata validated with Pydantic                    | `run-name`, `description`, `tags`, `metadata` editable |
| `run.log`                               | UTF-8 stdout/stderr (Python, native FD, subprocess)     | Fixed                                                  |
| `metrics.parquet`                       | Optional 4-column table (`key/value/step/timestamp_ms`) | Fixed                                                  |
| `inputs/`, `outputs/`                   | Real files recorded in `run.yaml.artifacts`             | Fixed                                                  |
| `src/<entry>.py`                        | Exact copy of the entry script                          | Fixed                                                  |
| `src/diff.patch`                        | Optional binary diff against `HEAD` (omitted if clean)  | Fixed                                                  |
| `figs/`                                 | Real files; updated with `cherries add`                 | Editable                                               |
| `assets/`, `reports/`, `README.md/html` | Report materials (via `add` or direct filesystem ops)   | Editable                                               |

## `run.yaml` and Metrics

```yaml
project-id: phace-exp
run-id: 01a1d75a-947b-7abc-8def-0123456789ab
run-name: 10-run
description: Verified mesh point and cell counts after round-trip I/O.
start-time: "2026-11-15 08:00:00+08:00"
end-time: "2026-11-15 08:03:12+08:00"
tags: []
params:
  mesh: /work/phace-exp/exp/2026/11/15/example/data/mesh.vtu
commit: "0123456789abcdef0123456789abcdef01234567"
metadata: {}
artifacts:
  inputs:
    - name: mesh.vtu
      sha256: ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
      size: 3
  outputs: []
  figs: []
```

- `start-time` and `end-time` record local wall time at second precision with
  an explicit numeric UTC offset (`YYYY-mm-dd HH:MM:SS±HH:MM`). While running,
  `end-time` and `commit` are `null`.
- `artifacts` has `inputs`, `outputs`, and `figs` lists of `{name, sha256, size}`
  entries with unique relative POSIX paths. Registered directories flatten to
  files; empty directories are omitted; zero-byte files are kept.
- Metrics append and flush to `metrics.jsonl` during execution, then convert to
  `metrics.parquet` (`String`, `Float64`, `Int64`, `Int64`) at `end()` and
  delete the JSONL file. Non-finite floats (`NaN`, `Infinity`, `-Infinity`) are
  encoded as strings in JSONL and restored as floats in Parquet.

## Source Capture (`HEAD` + `src/diff.patch`)

Cherries runs a fast Git preflight check in `start()` (failing immediately
before expensive computation) and captures the final source state in `end()`,
without modifying `HEAD`, branches, the staging index, or `.git/refs/`:

1. Requires the repository to have a `HEAD` commit.
2. Checks submodules reported by `git status`: clean submodules are allowed;
   any dirty submodule (modified, staged, untracked, or nested dirty) fails
   with an error.
3. Collects modified, deleted, and untracked non-ignored paths relative to
   `HEAD`, excluding `cherries/` and study `data/`, `figs/`, `tmp/`.
4. Checks `git check-attr filter` on changed/new files: committed clean Git LFS
   files are allowed; any dirty or untracked Git LFS file fails with an error.
5. Stages the remaining changes in a temporary `GIT_INDEX_FILE` initialized
   from `HEAD` and writes `git diff --cached --binary --no-ext-diff HEAD` to
   `src/diff.patch` when non-empty.

To reproduce a run's code, run `git checkout <commit>` and (if present)
`git apply src/diff.patch`.

## Artifact Lineage and Pruning

- Each run's non-empty (`size > 0`) `outputs` and `figs` SHA-256 digests form
  its produced set; non-empty `inputs` digests form its consumed set.
  Zero-byte files are ignored so unrelated runs are never falsely linked.
- Starting from seed runs (explicit IDs/paths and/or `--tag`), `lineage`
  computes the transitive ancestor closure. `prune` keeps that closure and
  deletes all other completed runs (refusing if zero runs match the seeds;
  plus `.tmp` runs locally when `--unfinished` is passed).

## Debug Mode and Reports

- `DEBUG=1 python src/10-run.py` (exact `DEBUG=1` at start): constructs
  `Config` and runs `main` once, returns `None`, leaves stdout/stderr in the
  terminal, skips Git checks and recording, and works outside Git.
- Save a single run report as `README.md` or `README.html` at the run root; use
  `reports/` only when a run has multiple reports. Store report images in
  `assets/` and reference them via relative paths (`assets/plot.png` from root
  `README`, `../assets/plot.png` from `reports/`).

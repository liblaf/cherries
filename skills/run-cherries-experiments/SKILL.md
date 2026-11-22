---
name: run-cherries-experiments
description: Record and analyze Python experiments with Cherries local runs, diff.patch source capture, artifact lineage pruning, and Restic archives.
---

# Cherries experiments

Read the study README and existing run README/reports before continuing research.
Use `<repo>/exp/YYYY/mm/dd/<study>/src/<script>.py`, with working inputs/outputs
in `data/`, figures in `figs/` and debug intermediates in `tmp/`. Define all
parameters in the script using `cherries.BaseConfig`, and end with
`cherries.run(main)`. `input`/`output`/`fig` return absolute paths inside
`data/` or `figs/`; `tmp` uses `tmp/` and is never collected. Ignore `data/`,
`figs/`, `tmp/` and repository `cherries/` in Git.

During normal recording, Cherries checks Git state at `start()` and captures
`HEAD` plus optional `src/diff.patch` at `end()` (excluding `cherries/` and
study `data/`/`figs/`/`tmp/`), without touching `HEAD`, branches or the staging
index. Dirty Git LFS files and dirty Git submodules are rejected; committed LFS
files and clean submodules are allowed. Use `DEBUG=1 python src/10-run.py` to
run once without recording or requiring Git.

Local runs live in `<repo>/cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/` (date taken
strictly from `run.yaml` `start-time`). Because local runs are ordinary folders,
use `cherries path RUN` to locate a run for direct `ls`/`cp`/reading,
`cherries list`/`show` to query metadata, `cherries edit` for
descriptions/tags/metadata, and `cherries add` for post-run `figs/`, `assets/`,
`reports/`, `README.md` or `README.html`.

Maintain the study README and each run's `README.md` (or `README.html` for
complex/interactive layouts) with evidence and interpretation; use `reports/`
only when a run has multiple reports, save report images in `assets/`, and
reference them via relative paths (`assets/img.png` or `../assets/img.png`).

Use `cherries lineage` and `cherries prune` (with explicit run IDs and/or
`--tag`) to trace and retain transitive SHA-256 artifact dependencies and remove
unused runs (works locally and with `--remote`). Prefer pruning locally before
archiving.

Use `cherries --remote RESTIC_REPO push RUN` to archive each run as one Restic
snapshot tagged `cherries,project:<project-id>,run:<UUIDv7>`, and `pull RUN` to
restore it locally. Remote snapshots are immutable: edit/add locally and
re-push. Use `--remote` with `list`/`show`/`lineage`/`prune`/`remove`/`gc`.
Verify local runs with `cherries verify RUN` and remote archives with
`restic -r REPO check`.

---
name: run-cherries-experiments
description: Record and analyze Python experiments with Cherries local runs and shared remote archives.
---

# Cherries experiments

Read the study README and existing run README/reports before continuing research.
Use `<repo>/exp/YYYY/mm/dd/<study>/src/<script>.py`, with working inputs/outputs
in `data/`, figures in `figs/` and debug intermediates in `tmp/`. Prepare inputs before execution. Define all
parameters in the script using `cherries.BaseConfig`, and end the entry script
with `cherries.run(main)`. input/output/fig immediately return absolute paths;
paths must remain under the corresponding study `data/` or `figs/` root, even
when absolute. Prepare outside files there first. end copies registered files into
`<repo>/cherries/runs/YYYY/mm/dd/<UUIDv7>/` and hashes the saved copies. The required
`run.yaml.artifacts` contains `inputs`, `outputs` and `figs` lists; each entry has
exactly `name`, `sha256` and `size`. Names are relative POSIX paths within the
role root and unique per role. Directory registrations flatten to files; empty
roles are `[]`, empty directories are omitted and zero-byte files are retained.

Use `cherries.tmp("debug/intermediate.vtu")` for an absolute path under study
`tmp/` with parent creation. Paths must stay inside that root. These files are
never registered or collected, during normal recording or debugging. Ignore
study `data/`, `figs/`, `tmp/` and repository `cherries/`; Git snapshots exclude
these paths even when already tracked.

Run `DEBUG=1 python src/10-run.py` for debugging without recording. Only exact
`DEBUG=1` at start selects this mode for the execution. Config is constructed and
main runs once; params are not serialized. No run directory, logs, metrics,
metadata, artifact copies or Git snapshot are created; Git is not required.
Console output stays visible and original exceptions propagate. Path helpers
still use the study workspace. Metrics do nothing; step starts at zero and
get_step/set_step work. Manual start/end supports the same mode. run returns
None in debug and the saved directory Path during normal recording.

Run scripts directly with Python. Use `cherries list/show/files/get` to inspect
results. After meaningful results, decisions or corrections, actively maintain
the study README and the run's README/reports, with evidence and interpretation.
Use Markdown normally and HTML for complex layout or interaction. When a run has
one report, save it as `README.md` or `README.html` at the run root. Use
`reports/` only for additional reports when the run has multiple reports. The
README can serve as an entry point linking detailed reports without repeating
their text. Save report images in the run's `assets/`; reference `assets/image.png`
from the root README and `../assets/image.png` from a report directly inside
`reports/`, adjusting relative paths for deeper report folders. Use `cherries edit`
for descriptions/tags and `cherries add` for figs/assets/reports/README.
Execution inputs, outputs, their manifest entries, src, params, log, metrics and
Git ref stay fixed. Only `figs` is editable within `artifacts`.

Local runs use `<repo>/cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`; remote runs use
`ROOT/projects/<project-id>/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`. Take the date strictly
from the persisted `run.yaml` `start-time` in its original local timezone, never
from UUID, study paths, end-time or the current clock. Finishing after midnight
and transferring across timezones keep that partition. UUIDv7 remains the ID;
CLI RUN accepts the ID or a concrete run path. `list` defaults to completed runs;
`list --unfinished` selects `.tmp` records. Only this daily layout is supported,
without historical flat-layout compatibility or a remote index. Create date
folders as needed; `remove` prunes empty day/month/year parents and empty `runs/`,
stopping before the local `cherries/` root or remote project root.
CAS stays at `ROOT/objects/sha256/ab/cd/<digest>`; Git refs stay at
`refs/cherries/runs/<id>`, and native source Git repositories keep their locations.

Use `cherries --remote ROOT push RUN` to archive and `pull RUN` to retrieve.
Remote records omit physical inputs/outputs/figs folders; files/get/pull resolve
logical paths from YAML and extensionless CAS objects. Logs, Parquet, the entry
script and editable reports/assets remain ordinary files. `.lfs` is an ordinary
data suffix; source Git/LFS keeps its native behavior. Save payloads before
atomically publishing YAML. Figures merge by name, retaining destination-only
figures. Preserve original local-offset start/end strings during synchronization.
Verify actual saved bytes against recorded hashes and sizes before claiming
recovery. `remove` deletes one record copy; remote `gc` reclaims CAS only after
scanning YAML manifests across all projects, including `.tmp`. Derived-content
lineage and prune remain proposals.
The storage specification and CLI reference define the exact supported format.

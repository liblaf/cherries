# Cherries

Run experiments directly with `cherries.run(main)` and keep records as ordinary
files, with Git snapshots and an optional shared remote CAS. `run.yaml.artifacts`
records input, output and figure names, SHA-256 digests and sizes; local runs keep
real files, while remote runs resolve those logical paths through the CAS.

Local records live in `cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`; remote records
live in `ROOT/projects/<project-id>/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/`. The date is
the original local date in the persisted `run.yaml` `start-time`, preserved when
a run ends after midnight or moves across timezones. CLI commands accept a run ID
or its directory path; `list --unfinished` selects records with the `.tmp` suffix.

Use `cherries.tmp("debug/intermediate.txt")` for files under the study's `tmp/`
that are never collected or included in Git snapshots. Run
`DEBUG=1 python src/10-run.py` to execute once without recording: path helpers
still work, metrics are ignored and console output stays visible. `run(main)`
returns `None` in this mode and a saved directory `Path` during normal recording.

- [Python API](design/cherries/api.pyi)
- [Example](design/cherries/example.py)
- [Storage and workflow](design/cherries/storage.md)
- [Management CLI](design/cherries/cli.md)
- [API reference](reference/liblaf/cherries/README.md)

---
name: run-cherries-experiments
description: Create, run, analyze, and report Python experiments with liblaf.cherries. Use when Codex needs to add or execute scripts under exp/yyyy/mm/dd/group-name/src/, use Cherries config, metric, path, name, and tag APIs, capture generated assets, or write reports under exp/yyyy/mm/dd/group-name/docs/ using the Cherries Experiment Summary.
---

# Run Cherries Experiments

## Shape

Use Cherries as the experiment runner and run evidence source. A normal group is:

```text
exp/yyyy/mm/dd/group-name/
├── src/10-script-name.py
├── data/
├── logs/
├── tmp/
└── docs/10-report-name.md
```

Use the current local date unless the user gives another date. Put scripts in `src/` and reports in sibling `docs/`, both with numbered prefixes.

## Script

Prefer this pattern:

```python
import logging
from pathlib import Path

from liblaf import cherries

logger = logging.getLogger(__name__)


class Config(cherries.BaseConfig):
    output: Path = cherries.output("result.txt", mkdir=True)


def main(cfg: Config) -> None:
    for step in range(10):
        cherries.set_step(step)
        cherries.log_metrics({"loss": 1 / (step + 1)})
    cfg.output.write_text("done\n")
    logger.info("Wrote %s", cfg.output)


if __name__ == "__main__":
    cherries.main(main)
```

- Use `cherries.BaseConfig`; `cherries.main()` logs config automatically.
- Pass config overrides as kebab-case CLI args, e.g. `--learning-rate 0.01` for `learning_rate`.
- Use normal `logging` for progress and notes.
- Use `cherries.input()`, `cherries.output()`, `cherries.temp()`, and `cherries.asset()` for files Cherries should record. The helpers queue paths, so create the files before exit.
- Use `cherries.log_metric(s)` and `cherries.set_step()` for metrics.
- Do not hardcode `profile="debug"` in scripts.

## Run

Run from the experiment group so `cwd` and `cmd` are readable:

```bash
cd exp/yyyy/mm/dd/group-name
DEBUG=1 CHERRIES_NAME="human readable run name" CHERRIES_TAGS="tag-a,tag-b" uv run python src/10-script-name.py --example-config value
```

- Use `CHERRIES_NAME` and comma-separated `CHERRIES_TAGS` for readable run identity.
- Use `DEBUG=1` only for quick exploratory runs; omit it for long, expensive, or valuable runs so Comet records the experiment.
- If `uv run` is unsuitable, use the active Python interpreter, but still run the script directly.
- Preserve terminal output or inspect `logs/*.log`.

## Report

After a run with results, write:

```text
exp/yyyy/mm/dd/group-name/docs/10-report-name.md
```

Include purpose, command, config, results, assets, analysis, and reproducibility notes. Interpret results, compare with expectations or baselines when possible, and call out anomalies, limitations, failed assumptions, and useful next experiments.

Include the YAML block introduced by `Cherries Experiment Summary:` from the terminal or `logs/*.log`. Do not use the later `Comet.ml Experiment Summary` as the required Cherries summary; mention Comet only as an external tracking link when useful.

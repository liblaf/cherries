---
name: run-cherries-experiments
description: Create, modify, run, inspect, analyze, and report Python experiments that use liblaf.cherries. Use when Codex needs to work under exp/YYYY/mm/dd/group-name/, write or edit numbered scripts in src/, run them with CHERRIES_NAME and CHERRIES_TAGS, inspect Cherries/Comet logs and generated assets, or write Markdown reports in docs/.
---

# Run Cherries Experiments

## Workflow

Use Cherries as the experiment runner and the run evidence source.

1. Turn the user's request into an experiment group:

   ```text
   exp/<YYYY>/<mm>/<dd>/<group-name>/
   ├── src/10-<script-name>.py
   ├── data/
   ├── logs/
   ├── tmp/
   └── docs/10-<report-name>.md
   ```

2. Use the current local date unless the user gives another date. Use `10-` for the first script/report in a group, or follow the next numbered local convention when extending an existing group.
3. Create or modify the script under `src/` before running it. Keep outputs under Cherries-managed paths instead of ad hoc repo paths.
4. Run the script with a human-readable `CHERRIES_NAME` and comma-separated `CHERRIES_TAGS`.
5. Wait for the process and Cherries shutdown hooks to finish. Preserve the terminal output; if it is unavailable, inspect `logs/*.log` and `.cherries/runs/**/logs/*.log`.
6. Read the generated `data/`, `tmp/`, `logs/`, and relevant `.cherries/runs/` snapshot files.
7. Write the report under `docs/` with the command, Comet/Cherries summary, observed outputs, analysis, limitations, and reproducibility notes.

## Script Pattern

Prefer this shape:

```python
import logging
from pathlib import Path

from liblaf import cherries

logger = logging.getLogger(__name__)


class Config(cherries.BaseConfig):
    output: Path = cherries.output("result.txt", mkdir=True)
    steps: int = 10


def main(cfg: Config) -> None:
    for step in range(cfg.steps):
        cherries.set_step(step)
        cherries.log_metrics({"train/loss": 1 / (step + 1)})

    cfg.output.write_text("done\n")
    logger.info("Wrote %s", cfg.output)


if __name__ == "__main__":
    cherries.main(main)
```

Use these Cherries conventions:

- Use `cherries.BaseConfig` for typed settings; `cherries.main()` instantiates it and logs the model as parameters.
- Pass config overrides as kebab-case CLI flags, for example `--learning-rate 0.01` for a `learning_rate` field.
- Use normal `logging` for progress and notes; Cherries writes the run log under `logs/`.
- Use `cherries.input()` for existing inputs under `data/`; it logs immediately.
- Use `cherries.output()` for outputs under `data/` and `cherries.temp()` for temporary artifacts under `tmp/`; they queue paths and log existing files at run end.
- Use `cherries.log_asset()`, `cherries.log_input()`, `cherries.log_output()`, or `cherries.log_temp()` only when logging an already-created path outside the helper defaults.
- Use `cherries.set_step()`, `cherries.log_metric()`, and `cherries.log_metrics()` for scalar metrics. Nested metric mappings flatten with `/`, such as `train/loss`.
- Do not hardcode `profile="debug"` in the script. Select debug/default behavior from the run command.

## Run Commands

Run from the experiment group so Cherries records a readable command and resolves paths below that group:

```bash
cd exp/<YYYY>/<mm>/<dd>/<group-name>
CHERRIES_NAME="Human readable run name" CHERRIES_TAGS="tag-a,tag-b" uv run python src/10-<script-name>.py --example-config value
```

For a quick local smoke run, add `DEBUG=1` to select the debug profile. Debug keeps local snapshots and logs, but disables remote Comet recording and Git commits. For the report-worthy run that should produce the normal Comet.ml summary, omit `DEBUG=1` unless the user asked for a local-only run.

If `uv run` is unsuitable in the target repo, use the active Python interpreter, but still run the script directly and keep the same environment variables.

## Inspect Results

After the run exits:

- Confirm expected outputs exist under `data/` and temporary artifacts under `tmp/`.
- Read `logs/10-<script-name>.log`; also inspect `.cherries/runs/` when local snapshots contain copied source, logs, or assets needed for the report.
- Use actual generated files as evidence. Do not rely only on terminal summaries when artifacts are available.
- If the process appears idle near Comet shutdown, verify whether files and logs have already been written before deciding the run failed.

## Report

Write the report at:

```text
exp/<YYYY>/<mm>/<dd>/<group-name>/docs/10-<report-name>.md
```

Include these sections when applicable:

- Purpose: what the experiment tested and why.
- Command: exact working directory, environment variables, script command, and important CLI overrides.
- Summary: the `Comet.ml Experiment Summary` block from terminal output or logs when present; include any Cherries metadata such as name, tags, entrypoint, experiment directory, Git SHA, and Comet URL.
- Outputs and assets: generated files, tables, plots, model artifacts, logs, and where they live.
- Results: metrics, qualitative observations, and comparisons with baselines or expectations.
- Analysis: interpretation, anomalies, failure modes, limitations, and what evidence supports the conclusion.
- Reproducibility: current git state when relevant, dependency/runtime notes, random seeds, and follow-up experiments.

Write the report after reading the assets and logs, not from the intended design alone.

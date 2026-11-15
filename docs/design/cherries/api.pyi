# Copyright (c) 2026 liblaf
# Reader-facing design specification: explanatory stub docstrings are intentional.
# ruff: noqa: PYI021
"""Cherries public API; see storage.md for repository layout and shared rules.

The entry script is <study>/src/<script>.py. Its location determines study;
the enclosing Git root determines local storage and the default project_id.
input/output/fig return absolute paths and register files for copying at end(),
whether called in a config class or main(). Registrations begin at script load.
Paths must remain under study/data (input/output) or study/figs (fig), including
absolute arguments. Prepare outside files in that root before registering them.
tmp uses study/tmp with the same root restriction and parent creation, but never
registers files. Git snapshots exclude study data/figs/tmp, including tracked files.
Local records use reflinks with copy fallback, then hash the saved copies into
run.yaml.artifacts (inputs/outputs/figs lists of name, sha256, size). Directory
registrations flatten to files; empty directories are omitted. CLI push/pull
resolve the same names through remote CAS; remote runs have no artifact folders.
Each run's src/ contains only its entry script under the original filename.
Run times use the machine's local timezone at each instant, with second precision
and explicit offsets (YYYY-mm-dd HH:MM:SS±HH:MM). Running end-time is null;
push/pull retain the exact strings across destination timezones.
Local runs use <repo>/cherries/runs/YYYY/mm/dd/<UUIDv7>[.tmp]/. The date is the
original local date in persisted run.yaml start-time; finishing after midnight
or transferring across timezones keeps that partition.
"""

from collections.abc import Callable, Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import Any

from pydantic import BaseModel

type Pathish = str | PathLike[str]

class BaseConfig(BaseModel):
    """A regular Pydantic model for parameters defined in the experiment script."""

def run[ConfigT: BaseConfig](
    main: Callable[[ConfigT], None] | Callable[[], None],
    *,
    project_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> Path | None:
    """Start, call main, end, and return the saved local run directory.

    For main(cfg: Config), construct Config() and save model_dump(mode="json")
    as params, then pass that instance to main. For main(), params is {}.
    name defaults to the entry script stem; description=None omits its YAML key.
    Exact DEBUG=1 at start instead constructs Config and invokes main once without
    serialization or recording, returning None. Console output remains visible;
    exceptions propagate. No Git repository is required in debug mode.
    """

def start(
    *,
    project_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    tags: Sequence[str] = (),
    params: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Start at step zero, retaining paths registered at load.

    Exact DEBUG=1 selects no-recording mode for this execution; later environment
    changes do not switch it. Otherwise record local start-time and begin a run.
    """

def end() -> None:
    """Record local end-time before copying files and writing Parquet and Git.

    Save registered files and record their relative names, SHA-256 and sizes.
    Store only src/<entry-filename> for source, then finalize the run directory.
    In debug mode, clear execution state without collecting or saving anything.
    """

def input(path: Pathish) -> Path:  # noqa: A001
    """Return absolute study/data/<path>; register it for copying into inputs/ at end."""

def output(path: Pathish) -> Path:
    """Return absolute study/data/<path>; create parents and copy into outputs/ at end."""

def fig(path: Pathish) -> Path:
    """Return absolute study/figs/<path>; create parents and copy into figs/ at end."""

def tmp(path: Pathish) -> Path:
    """Return absolute study/tmp/<path>; create parents; never collect this file."""

def log_metric(
    key: str,
    value: float,
    *,
    step: int | None = None,
    timestamp_ms: int | None = None,
) -> None:
    """Append and flush one metric; None uses the current step/time. No-op in debug."""

def log_metrics(
    metrics: Mapping[str, int | float],
    *,
    step: int | None = None,
    timestamp_ms: int | None = None,
) -> None:
    """Append metrics sharing step/time and flush once. No-op in debug."""

def get_step() -> int:
    """Return the active run's current step, initially zero."""

def set_step(step: int) -> None:
    """Set the active run's step; logging does not increment it."""

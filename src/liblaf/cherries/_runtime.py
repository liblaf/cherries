# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003
"""Record an ordinary Python experiment, with paths registered at script load."""

from __future__ import annotations

import ctypes
import inspect
import json
import math
import os
import sys
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO, cast, get_type_hints

import polars as pl
from pydantic import BaseModel

from . import _git
from ._io import (
    atomic_bytes,
    collect_artifacts,
    copy,
    empty_artifacts,
    now,
    run_relative_path,
    uuid7,
    write_yaml,
)

type Pathish = str | os.PathLike[str]
METRIC_SCHEMA = {
    "key": pl.String,
    "value": pl.Float64,
    "step": pl.Int64,
    "timestamp_ms": pl.Int64,
}
_entry: Path | None = None
_registered: dict[str, dict[Path, Path]] = {
    "inputs": {},
    "outputs": {},
    "figs": {},
}
_active: _Run | None = None
_debugging = False
_debug_step = 0


class BaseConfig(BaseModel):
    """Parameters defined in the experiment script, serialized as ordinary JSON."""


def _script() -> Path:
    global _entry  # noqa: PLW0603
    entry = Path(cast("str", sys.modules["__main__"].__file__)).resolve()
    if _entry != entry:
        for paths in _registered.values():
            paths.clear()
        _entry = entry
    return entry


def _path(role: str, path: Pathish) -> Path:
    base = _script().parent.parent / ("figs" if role == "figs" else "data")
    result = (base / path).resolve()
    name = result.relative_to(base)
    if name == Path():
        raise ValueError(f"Path must be inside {base}: {path}")
    if not _debugging:
        _registered[role][name] = result
    if role != "inputs":
        result.parent.mkdir(parents=True, exist_ok=True)
    return result


def input(path: Pathish) -> Path:  # noqa: A001
    """Return absolute study/data/path and register its end-of-run input copy."""
    return _path("inputs", path)


def output(path: Pathish) -> Path:
    """Return absolute study/data/path, create parents and register the output."""
    return _path("outputs", path)


def fig(path: Pathish) -> Path:
    """Return absolute study/figs/path, create parents and register the figure."""
    return _path("figs", path)


def tmp(path: Pathish) -> Path:
    """Return absolute study/tmp/path, creating parents without recording it."""
    base = _script().parent.parent / "tmp"
    result = (base / path).resolve()
    if result.relative_to(base) == Path():
        raise ValueError(f"Path must be inside {base}: {path}")
    result.parent.mkdir(parents=True, exist_ok=True)
    return result


class _Capture:
    """Capture Python, native and subprocess stdout/stderr in one ordinary file."""

    def __init__(self, path: Path) -> None:
        self.streams = sys.stdout, sys.stderr
        self._flush()
        self.saved = os.dup(1), os.dup(2)
        self.log = path.open("ab", buffering=0)
        os.dup2(self.log.fileno(), 1)
        os.dup2(self.log.fileno(), 2)
        self.redirected = tuple(
            os.fdopen(os.dup(fd), "w", encoding="utf-8", buffering=1) for fd in (1, 2)
        )
        sys.stdout, sys.stderr = self.redirected

    @staticmethod
    def _flush() -> None:
        sys.stdout.flush()
        sys.stderr.flush()
        ctypes.CDLL(None).fflush(None)

    def close(self) -> None:
        self._flush()
        for stream in self.redirected:
            stream.close()
        sys.stdout, sys.stderr = self.streams
        for fd, saved in zip((1, 2), self.saved, strict=True):
            os.dup2(saved, fd)
            os.close(saved)
        self.log.close()


@dataclass
class _Run:
    directory: Path
    repo: Path
    entry: Path
    metadata: dict[str, Any]
    capture: _Capture
    step: int = 0
    metrics: TextIO | None = field(default=None)


def _current() -> _Run:
    if _active is None:
        raise RuntimeError("No active Cherries run")
    return _active


def start(
    *,
    project_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    tags: Sequence[str] = (),
    params: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Begin at step zero; DEBUG=1 skips recording and retains workspace paths."""
    global _active, _debugging, _debug_step  # noqa: PLW0603
    if _active is not None:
        raise RuntimeError("A Cherries run is already active")
    _debugging = os.getenv("DEBUG") == "1"
    _debug_step = 0
    if _debugging:
        return
    start_time = now()
    entry = _script()
    repo = _git.root(entry.parent)
    _git.preflight(repo)
    run_id = uuid7()
    directory = (
        repo / "cherries" / "runs" / run_relative_path(run_id, start_time)
    ).with_name(f"{run_id}.tmp")
    directory.mkdir(parents=True)
    data = {
        "project-id": project_id or repo.name,
        "run-id": run_id,
        "run-name": name or entry.stem,
        "start-time": start_time,
        "end-time": None,
        "tags": list(tags),
        "params": dict(params or {}),
        "commit": None,
        "metadata": dict(metadata or {}),
        "artifacts": empty_artifacts(),
    }
    if description is not None:
        data["description"] = description
    write_yaml(directory / "run.yaml", data)
    _active = _Run(directory, repo, entry, data, _Capture(directory / "run.log"))
    print(f"Cherries started {run_id}", file=sys.stderr)


def _finish(*, publish: bool) -> Path:
    global _active  # noqa: PLW0603
    current = _current()
    try:
        current.metadata["end-time"] = now()
        write_yaml(current.directory / "run.yaml", current.metadata)
        for role, paths in _registered.items():
            collected = {}
            for name, source in paths.items():
                if publish or source.exists():
                    saved = copy(source, current.directory / role / name)
                    for entry in collect_artifacts(saved, name):
                        collected[entry["name"]] = entry
            current.metadata["artifacts"][role] = [
                collected[name] for name in sorted(collected)
            ]
            write_yaml(current.directory / "run.yaml", current.metadata)
        if current.metrics is not None:
            current.metrics.close()
            path = current.directory / "metrics.jsonl"
            pl.scan_ndjson(
                path,
                schema={**METRIC_SCHEMA, "value": pl.String},
            ).with_columns(pl.col("value").cast(pl.Float64)).select(
                list(METRIC_SCHEMA),
            ).sink_parquet(current.directory / "metrics.parquet")
            path.unlink()
        commit, patch = _git.capture(current.repo)
        current.metadata["commit"] = commit
        source_dir = current.directory / "src"
        copy(current.entry, source_dir / current.entry.name)
        if patch:
            atomic_bytes(source_dir / "diff.patch", patch)
        write_yaml(current.directory / "run.yaml", current.metadata)
        print(f"Cherries saved {current.metadata['run-id']}", file=sys.stderr)
    finally:
        if current.metrics is not None:
            current.metrics.close()
        current.capture.close()
        for paths in _registered.values():
            paths.clear()
        _active = None
    if publish:
        destination = current.directory.with_suffix("")
        current.directory.rename(destination)
        return destination
    return current.directory


def end() -> None:
    """Record end-time, then save files, metrics and Git state; finalize directory."""
    global _debugging  # noqa: PLW0603
    if _debugging:
        _debugging = False
        return
    _finish(publish=True)


def run(
    main: Callable[..., None],
    *,
    project_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> Path | None:
    """Execute main and return its saved directory, or None when DEBUG=1."""
    start(
        project_id=project_id,
        name=name,
        description=description,
        tags=tags,
        metadata=metadata,
    )
    try:
        if parameters := inspect.signature(main).parameters:
            config = get_type_hints(main)[next(iter(parameters))]()
            if not _debugging:
                current = _current()
                current.metadata["params"] = config.model_dump(mode="json")
                write_yaml(current.directory / "run.yaml", current.metadata)
            main(config)
        else:
            main()
    except BaseException as error:
        if _debugging:
            end()
            raise
        traceback.print_exc()
        try:
            _finish(publish=False)
        except Exception as recording_error:  # noqa: BLE001 - preserve the experiment failure
            error.add_note(f"Cherries recording failed: {recording_error}")
        raise
    if _debugging:
        end()
        return None
    return _finish(publish=True)


def log_metric(
    key: str,
    value: float,
    *,
    step: int | None = None,
    timestamp_ms: int | None = None,
) -> None:
    """Append and flush one metric using the current step and time by default."""
    log_metrics({key: value}, step=step, timestamp_ms=timestamp_ms)


def log_metrics(
    metrics: Mapping[str, int | float],
    *,
    step: int | None = None,
    timestamp_ms: int | None = None,
) -> None:
    """Append in mapping order, sharing step/time, and flush once without fsync."""
    if _debugging or not metrics:
        return
    current = _current()
    if current.metrics is None:
        current.metrics = (current.directory / "metrics.jsonl").open(
            "a", encoding="utf-8"
        )
    stamp = time.time_ns() // 1_000_000 if timestamp_ms is None else timestamp_ms
    for key, raw in metrics.items():
        value = float(raw)
        encoded = (
            value
            if math.isfinite(value)
            else {math.inf: "Infinity", -math.inf: "-Infinity"}.get(value, "NaN")
        )
        row = {
            "key": key,
            "value": encoded,
            "step": current.step if step is None else step,
            "timestamp_ms": stamp,
        }
        current.metrics.write(json.dumps(row, allow_nan=False) + "\n")
    current.metrics.flush()


def get_step() -> int:
    """Return the current step, initially zero."""
    return _debug_step if _debugging else _current().step


def set_step(step: int) -> None:
    """Set the current step; logging does not increment it."""
    global _debug_step  # noqa: PLW0603
    if _debugging:
        _debug_step = step
    else:
        _current().step = step

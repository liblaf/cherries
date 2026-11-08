# Copyright (c) 2026 liblaf
# Keep contextual errors beside the boundary whose invariant they describe.
# ruff: noqa: EM101, EM102, TRY003
"""Execution ownership, durable metric streams, and Python run contexts."""

from __future__ import annotations

import contextlib
import contextvars
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Self, SupportsFloat, TextIO

import polars as pl

from ._io import (
    ConflictError,
    IntegrityError,
    StoreError,
    atomic_bytes,
    contained,
    fsync_dir,
    now,
    process_identity,
    read_yaml,
    relative_path,
    uuid7,
    write_yaml,
)
from ._source import archive_snapshot, fingerprint_source

_CURRENT: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "cherries_current_run", default=None
)


def recover_metrics(directory: Path) -> dict[str, Any]:
    """Explicitly salvage a truncated final row, retaining its exact bytes."""
    path = directory / "metrics.jsonl"
    if not path.is_file():
        return {}
    offset = 0
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            try:
                _parse_metric(json.loads(raw), number)
            except (ValueError, UnicodeDecodeError, StoreError):
                if raw.endswith(b"\n"):
                    raise
                audit = directory / "recovery" / f"metrics-tail-{uuid7()}.bin"
                atomic_bytes(audit, raw)
                write_yaml(
                    audit.with_suffix(".yaml"),
                    {"source": "metrics.jsonl", "offset": offset, "bytes": len(raw)},
                )
                temporary = path.with_name(path.name + ".tmp")
                with path.open("rb") as original, temporary.open("wb") as prefix:
                    remaining = offset
                    while remaining:
                        block = original.read(min(remaining, 1024 * 1024))
                        if not block:
                            raise IntegrityError(
                                "metric stream changed during explicit recovery"
                            ) from None
                        prefix.write(block)
                        remaining -= len(block)
                    prefix.flush()
                    os.fsync(prefix.fileno())
                temporary.replace(path)
                fsync_dir(directory)
                return {
                    "source": str(path),
                    "truncated_bytes": len(raw),
                    "audit": str(audit),
                }
            if not raw.endswith(b"\n"):
                with path.open("ab") as completed:
                    completed.write(b"\n")
                    completed.flush()
                    os.fsync(completed.fileno())
                return {"source": str(path), "completed_newline": True}
            offset += len(raw)
    return {}


_SPECIAL = {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}
_METRIC_SCHEMA = {
    "name": pl.String,
    "step": pl.Int64,
    "timestamp_ms": pl.Int64,
    "value": pl.Float64,
}


def _metric_value(value: float) -> float | str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _summarize(summary: dict[str, dict[str, Any]], name: str, value: float) -> None:
    item = summary.setdefault(
        name, {"last": None, "min": None, "max": None, "count": 0, "nonfinite_count": 0}
    )
    item["last"] = _metric_value(value)
    item["count"] += 1
    if math.isfinite(value):
        item["min"] = value if item["min"] is None else min(item["min"], value)
        item["max"] = value if item["max"] is None else max(item["max"], value)
    else:
        item["nonfinite_count"] += 1


def _parse_metric(row: Any, line: int) -> tuple[str, int | None, int, float]:
    if not isinstance(row, dict) or set(row) != set(_METRIC_SCHEMA):
        raise IntegrityError(f"invalid metric JSONL fields on line {line}")
    name = row["name"]
    step = row["step"]
    stamp = row["timestamp_ms"]
    value = row["value"]
    if not isinstance(name, str) or not name:
        raise IntegrityError(f"invalid metric name on line {line}")
    if step is not None and (type(step) is not int or not -(1 << 63) <= step < 1 << 63):
        raise IntegrityError(f"invalid metric step on line {line}")
    if type(stamp) is not int or not -(1 << 63) <= stamp < 1 << 63:
        raise IntegrityError(f"invalid metric timestamp on line {line}")
    if isinstance(value, str):
        if value not in _SPECIAL:
            raise IntegrityError(f"invalid metric value on line {line}")
        numeric = _SPECIAL[value]
    elif type(value) in {int, float} and math.isfinite(value):
        numeric = float(value)
    else:
        raise IntegrityError(f"invalid metric value on line {line}")
    return name, step, stamp, numeric


class MetricsWriter:
    """Append one record per metric and retain only bounded summary state."""

    def __init__(self, directory: Path, *, durability: str = "fsync") -> None:
        if durability not in {"fsync", "flush"}:
            raise ValueError("metric_durability must be 'fsync' or 'flush'")
        self.path = Path(directory) / "metrics.jsonl"
        self.durability = durability
        self.summary: dict[str, dict[str, Any]] = {}
        self.stream: TextIO | None = None
        if self.path.exists():
            for name, _, _, value in _metric_rows(self.path):
                _summarize(self.summary, name, value)
        created = not self.path.exists()
        self.stream = self.path.open("a", encoding="utf-8")
        if created and durability == "fsync":
            fsync_dir(self.path.parent)

    def append(
        self,
        values: Mapping[str, SupportsFloat],
        *,
        step: int | None = None,
        timestamp_ms: int | None = None,
    ) -> None:
        if self.stream is None:
            raise StoreError("metric writer is closed")
        stamp = time.time_ns() // 1_000_000 if timestamp_ms is None else timestamp_ms
        rows: list[tuple[str, float, str]] = []
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, SupportsFloat):
                raise TypeError(f"metric {name!r} must be numeric")
            numeric = float(value)
            row = {
                "name": name,
                "step": step,
                "timestamp_ms": stamp,
                "value": _metric_value(numeric),
            }
            _parse_metric(row, 0)
            rows.append(
                (
                    name,
                    numeric,
                    json.dumps(row, allow_nan=False, ensure_ascii=False) + "\n",
                )
            )
        for _, _, line in rows:
            self.stream.write(line)
        self.stream.flush()
        if self.durability == "fsync":
            os.fsync(self.stream.fileno())
        for name, numeric, _ in rows:
            _summarize(self.summary, name, numeric)

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.flush()
                if self.durability == "fsync":
                    os.fsync(self.stream.fileno())
            finally:
                self.stream.close()
                self.stream = None


def _metric_rows(path: Path) -> Iterator[tuple[str, int | None, int, float]]:
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                raise IntegrityError(
                    f"truncated metric JSONL line {number}; use explicit recovery"
                )
            try:
                row = json.loads(
                    line,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(value)
                    ),
                )
            except (ValueError, TypeError) as error:
                raise IntegrityError(
                    f"invalid metric JSONL line {number}: {error}"
                ) from error
            yield _parse_metric(row, number)


def finalize_metrics(directory: str | Path) -> dict[str, dict[str, Any]]:
    """Validate the JSONL stream and seal Parquet with fixed schema and row order.

    The original stream remains available until the publisher has confirmed the
    run directory. A failed conversion therefore preserves its recovery source.
    """
    directory = Path(directory)
    source = directory / "metrics.jsonl"
    if not source.exists():
        return {}
    summary: dict[str, dict[str, Any]] = {}
    count = 0
    for name, _, _, value in _metric_rows(source):
        _summarize(summary, name, value)
        count += 1
    if not count:
        return summary
    target = directory / "metrics.parquet"
    temporary = directory / "metrics.parquet.tmp"
    # Values are parsed as strings because JSONL intentionally encodes special
    # Float64 values as strings; the strict cast restores NaN and infinities.
    schema = {**_METRIC_SCHEMA, "value": pl.String}
    frame = (
        pl.scan_ndjson(source, schema=schema, low_memory=True)
        .with_columns(pl.col("value").cast(pl.Float64, strict=True))
        .select(list(_METRIC_SCHEMA))
    )
    try:
        frame.sink_parquet(
            temporary, maintain_order=True, sync_on_close="all", engine="streaming"
        )
        sealed = pl.scan_parquet(temporary)
        if sealed.collect_schema() != pl.Schema(_METRIC_SCHEMA):
            raise IntegrityError("sealed metric Parquet has an unexpected schema")  # noqa: TRY301
        if sealed.select(pl.len()).collect().item() != count:
            raise IntegrityError("metric JSONL and Parquet row counts differ")  # noqa: TRY301
        # Streaming aggregation checks summaries without collecting the history.
        groups = (
            sealed.group_by("name", maintain_order=True)
            .agg(
                pl.col("value").last().alias("last"),
                pl.col("value").filter(pl.col("value").is_finite()).min().alias("min"),
                pl.col("value").filter(pl.col("value").is_finite()).max().alias("max"),
                pl.len().alias("count"),
                (~pl.col("value").is_finite()).sum().alias("nonfinite_count"),
            )
            .collect(engine="streaming")
        )
        sealed_summary: dict[str, dict[str, Any]] = {}
        for row in groups.iter_rows(named=True):
            name = row.pop("name")
            row["last"] = _metric_value(row["last"])
            sealed_summary[name] = row
        if summary != sealed_summary:
            raise IntegrityError("metric JSONL and Parquet summaries differ")  # noqa: TRY301
        temporary.replace(target)
        fsync_dir(directory)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    return summary


class _LogTee:
    def __init__(self, console: Any, log: TextIO) -> None:
        self.console = console
        self.log = log
        self.console_enabled = True

    def write(self, text: str) -> int:
        written = self.log.write(text)
        self.log.flush()
        if self.console_enabled:
            try:
                self.console.write(text)
            except BrokenPipeError:
                self.console_enabled = False
        return written

    def flush(self) -> None:
        self.log.flush()
        if self.console_enabled:
            try:
                self.console.flush()
            except BrokenPipeError:
                self.console_enabled = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.console, name)


def _persist(draft: Any) -> None:
    draft.metadata["updated_at"] = now()
    write_yaml(Path(draft.directory) / "run.yaml", draft.metadata)


def _refresh(draft: Any) -> None:
    metadata = read_yaml(Path(draft.directory) / "run.yaml")
    draft.metadata.clear()
    draft.metadata.update(metadata)


def _settings(project: Any) -> dict[str, Any]:
    return getattr(project, "settings", {}).get("recording", {})


def _begin(draft: Any, execution: dict[str, Any]) -> str:
    if draft.metadata.get("status") not in {None, "prepared"}:
        raise ConflictError(f"run {draft.id} is not prepared")
    boundary = fingerprint_source(draft.project)
    draft.metadata.update(status="running", started_at=now(), execution=execution)
    draft.metadata["recording_owner"] = process_identity()
    draft.metadata["git"] = {"start_fingerprint": boundary, "replay_verified": False}
    # Prepared inputs are independent ordinary copies. Their content identity
    # was fixed at registration; marking consumed preserves that evidence.
    for field in ("sources", "input_bindings", "directory_bindings"):
        for binding in draft.metadata.get(field, []):
            binding["consumed"] = True
    _persist(draft)
    return boundary


def _freeze_source(draft: Any, execution: dict[str, Any], start: str) -> dict[str, Any]:
    _refresh(draft)
    draft.metadata.update(status="finalizing", ended_at=now(), execution=execution)
    _persist(draft)
    end = fingerprint_source(draft.project)
    git = archive_snapshot(draft.project, draft.id)
    git.update(
        start_fingerprint=start,
        end_fingerprint=end,
        source_stable=start == end,
        replay_verified=False,
    )
    draft.metadata["git"] = git
    _persist(draft)
    return git


def _finish(draft: Any, execution: dict[str, Any], start: str) -> Any:
    git = _freeze_source(draft, execution, start)
    metrics = finalize_metrics(draft.directory)
    return draft.save(
        status=execution["status"], execution=execution, git=git, metrics=metrics
    )


def _exception_status(error: BaseException | None) -> tuple[str, int]:
    if error is None or (
        isinstance(error, SystemExit) and (error.code is None or error.code == 0)
    ):
        return "succeeded", 0
    if isinstance(error, KeyboardInterrupt):
        return "cancelled", 130
    if isinstance(error, SystemExit):
        return "failed", error.code if type(error.code) is int else 1
    return "failed", 1


def _attach_recording_error(
    error: BaseException, recording_error: BaseException, result: Any = None
) -> None:
    error.add_note(f"Cherries could not complete recording: {recording_error}")
    with contextlib.suppress(AttributeError, TypeError):
        error.recording_error = recording_error
        error.run_result = result or getattr(recording_error, "result", None)


def _failure_result(draft: Any, execution: dict[str, Any], error: BaseException) -> Any:
    result = getattr(error, "result", None)
    if result is None:
        result = draft._result(  # noqa: SLF001 - shared persistence/runtime result factory.
            execution_status=execution.get("status", "failed"),
            exit_code=execution.get("exit_code"),
            warnings=[f"recording incomplete: {error}"],
        )
        with contextlib.suppress(AttributeError, TypeError):
            error.result = result
    return result


class RunContext:
    """Record one Python execution or attach helpers to a CLI-owned execution."""

    def __init__(
        self,
        project: Any,
        *,
        name: str,
        kind: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        tags: Sequence[str] = (),
        on_error: str | None = None,
        metric_durability: str | None = None,
    ) -> None:
        self.project = project
        self.name = name
        self.kind = kind
        self.parameters = dict(parameters or {})
        self.tags = list(tags)
        settings = _settings(project)
        self.on_error = on_error or settings.get("on_error", "keep")
        self.metric_durability = metric_durability or settings.get(
            "metric_durability", "fsync"
        )
        if self.on_error not in {"keep", "discard"}:
            raise ValueError("on_error must be 'keep' or 'discard'")
        self.draft: Any = None
        self.result: Any = None
        self._active = False
        self._used = False
        self._attached = False
        self._metrics: MetricsWriter | None = None
        self._step: int | None = None
        self._stack = contextlib.ExitStack()
        self._token: contextvars.Token | None = None
        self._boundary = ""
        self._log: TextIO | None = None

    @property
    def id(self) -> str:
        if self.draft is None:
            raise StoreError("run context has not started")
        return self.draft.id

    @property
    def directory(self) -> Path:
        if self.draft is None:
            raise StoreError("run context has not started")
        return Path(self.draft.directory)

    @property
    def params(self) -> dict[str, Any]:
        self._require_active()
        return dict(self.draft.metadata.get("parameters", {}))

    def _require_active(self) -> None:
        if not self._active:
            raise StoreError("no active run context")

    def _attach(self, run_id: str) -> None:
        expected = os.environ.get("CHERRIES_PROJECT")
        expected_store = os.environ.get("CHERRIES_STORE")
        if expected and expected != self.project.id:
            raise ConflictError(
                "attached run project conflicts with the execution controller"
            )
        if (
            expected_store
            and Path(expected_store).resolve()
            != Path(self.project.store.root).resolve()
        ):
            raise ConflictError(
                "attached run store conflicts with the execution controller"
            )
        self.draft = self.project.runs.draft(run_id)
        expected_directory = os.environ.get("CHERRIES_RUN_DIR")
        if (
            expected_directory
            and Path(expected_directory).resolve() != self.directory.resolve()
        ):
            raise ConflictError(
                "attached run directory conflicts with the execution controller"
            )
        metadata = self.draft.metadata
        if metadata.get("status") != "running":
            raise ConflictError("only an active controller-owned run can be attached")
        if self.kind is not None and self.kind != metadata.get("kind", "simulation"):
            raise ConflictError(
                "attached run kind conflicts with the execution controller"
            )
        self.kind = metadata.get("kind", "simulation")
        existing = metadata.get("parameters", {})
        for key, value in self.parameters.items():
            if key in existing and existing[key] != value:
                raise ConflictError(f"attached run parameter conflicts: {key}")
        metadata.setdefault("parameters", {}).update(self.parameters)
        metadata["tags"] = list(dict.fromkeys([*metadata.get("tags", []), *self.tags]))
        _persist(self.draft)
        self._attached = True

    def __enter__(self) -> Self:
        if self._used or self._active:
            raise StoreError("a run context can only be entered once")
        if current_run() is not None:
            raise ConflictError("a run context is already active")
        self._used = True
        run_id = os.environ.get("CHERRIES_RUN_ID")
        if run_id:
            self._attach(run_id)
        else:
            self.kind = self.kind or "simulation"
            self.draft = self.project.runs.create(
                name=self.name,
                kind=self.kind,
                parameters=self.parameters,
                tags=self.tags,
            )
            self._boundary = _begin(
                self.draft, {"observed_by": "python", "argv": list(sys.argv)}
            )
        self._active = True
        try:
            self._metrics = MetricsWriter(
                self.directory, durability=self.metric_durability
            )
            # The outer process already captures the child's native streams.
            # Opening the same log in an attached child would duplicate writes.
            if not self._attached:
                self._log = self._stack.enter_context(
                    (self.directory / "run.log").open("a", encoding="utf-8")
                )
                self._stack.enter_context(
                    contextlib.redirect_stdout(_LogTee(sys.stdout, self._log))
                )
                self._stack.enter_context(
                    contextlib.redirect_stderr(_LogTee(sys.stderr, self._log))
                )
            self._token = _CURRENT.set(self)
        except BaseException:
            self._active = False
            self._stack.close()
            raise
        return self

    def __exit__(  # noqa: C901, PLR0912, PLR0915 - one lifecycle boundary preserves primary exceptions.
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        recording_error: BaseException | None = None
        try:
            if error is not None and self._log is not None:
                traceback.print_exception(error_type, error, tb, file=self._log)
            if self._metrics is not None:
                self._metrics.close()
            if self._log is not None:
                self._log.flush()
                os.fsync(self._log.fileno())
        except BaseException as failure:  # noqa: BLE001 - preserve experiment exceptions during recording failures.
            recording_error = failure
        finally:
            self._active = False
            if self._token is not None:
                _CURRENT.reset(self._token)
            try:
                self._stack.close()
            except BaseException as failure:  # noqa: BLE001
                recording_error = recording_error or failure
        if self._attached:
            if recording_error is not None:
                if error is not None:
                    _attach_recording_error(error, recording_error)
                else:
                    raise recording_error
            return False
        status, exit_code = _exception_status(error)
        execution = {
            "observed_by": "python",
            "argv": list(sys.argv),
            "status": status,
            "exit_code": exit_code,
        }
        if error is not None:
            execution["exception"] = {
                "type": type(error).__qualname__,
                "message": str(error),
            }
        if status != "succeeded" and self.on_error == "discard":
            try:
                shutil.rmtree(self.directory)
                fsync_dir(self.directory.parent)
                self.result = self.draft._result(  # noqa: SLF001
                    execution_status=status,
                    exit_code=exit_code,
                    durability="confirmed",
                    discarded=True,
                    warnings=["unpublished run discarded by on_error policy"],
                )
            except BaseException as failure:  # noqa: BLE001
                recording_error = recording_error or failure
        else:
            try:
                if recording_error is not None:
                    self.draft.metadata.setdefault("diagnostics", []).append(
                        str(recording_error)
                    )
                    _persist(self.draft)
                    _freeze_source(self.draft, execution, self._boundary)
                else:
                    self.result = _finish(self.draft, execution, self._boundary)
            except BaseException as failure:  # noqa: BLE001
                recording_error = recording_error or failure
                self.result = getattr(failure, "result", None)
        if recording_error is not None and self.result is None:
            self.result = _failure_result(self.draft, execution, recording_error)
        if error is not None:
            with contextlib.suppress(AttributeError, TypeError):
                error.run_result = self.result
            if recording_error is not None:
                _attach_recording_error(error, recording_error, self.result)
            return False
        if recording_error is not None:
            raise recording_error
        return False

    def input(self, source: Any, *, name: str | None = None) -> Path:
        self._require_active()
        if name is None:
            value = getattr(source, "path", source)
            name = Path(value).name
        logical = "inputs/" + relative_path(name)
        return self.project.store.bind_input(self.draft, source, logical, consumed=True)

    def _path(self, role: str, name: str | Path, *, required: bool = False) -> Path:
        self._require_active()
        logical = f"{role}/{relative_path(name)}"
        path = contained(self.directory, logical)
        path.parent.mkdir(parents=True, exist_ok=True)
        if required:
            outputs = self.draft.metadata.setdefault("required_outputs", [])
            if logical not in outputs:
                outputs.append(logical)
                _persist(self.draft)
        return path

    def output(self, name: str | Path, *, required: bool = True) -> Path:
        return self._path("outputs", name, required=required)

    def figure(self, name: str | Path, *, required: bool = True) -> Path:
        return self._path("figs", name, required=required)

    def asset(self, name: str | Path, *, source: str | Path | None = None) -> Path:
        path = self._path("assets", name)
        if source is not None:
            shutil.copyfile(Path(source), path)
        return path

    def report(self, name: str | Path = "README.md") -> Path:
        self._require_active()
        logical = relative_path(name)
        if logical not in {"README.md", "README.html"} and not logical.startswith(
            "reports/"
        ):
            logical = "reports/" + logical
        path = contained(self.directory, logical)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def scratch(self, name: str | Path) -> Path:
        return self._path("scratch", name)

    def log_metric(
        self,
        name: str,
        value: SupportsFloat,
        *,
        step: int | None = None,
        timestamp_ms: int | None = None,
    ) -> None:
        self.log_metrics({name: value}, step=step, timestamp_ms=timestamp_ms)

    def log_metrics(
        self,
        values: Mapping[str, SupportsFloat],
        *,
        step: int | None = None,
        timestamp_ms: int | None = None,
    ) -> None:
        self._require_active()
        assert self._metrics is not None
        self._metrics.append(
            values, step=self._step if step is None else step, timestamp_ms=timestamp_ms
        )

    def log_param(self, name: str, value: Any) -> None:
        self.log_params({name: value})

    def log_params(self, values: Mapping[str, Any]) -> None:
        self._require_active()
        existing = self.draft.metadata.setdefault("parameters", {})
        for name, value in values.items():
            if name in existing and existing[name] != value:
                raise ConflictError(f"run parameter is already fixed: {name}")
        existing.update(values)
        _persist(self.draft)

    def get_param(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    def get_params(self) -> dict[str, Any]:
        return self.params

    def get_metrics(self, metrics: Sequence[str] | None = None) -> pl.DataFrame:
        """Read current metric rows on explicit request, without a history buffer."""
        self._require_active()
        path = self.directory / "metrics.jsonl"
        rows = list(_metric_rows(path)) if path.exists() else []
        frame = pl.DataFrame(rows, schema=_METRIC_SCHEMA, orient="row")
        if metrics is not None:
            frame = frame.filter(pl.col("name").is_in(list(metrics)))
        return frame

    def get_metric(self, name: str) -> pl.DataFrame:
        return self.get_metrics([name])

    def set_step(self, step: int | None) -> None:
        self._require_active()
        if step is not None and (
            type(step) is not int or not -(1 << 63) <= step < 1 << 63
        ):
            raise ValueError("step must fit an Int64 or be None")
        self._step = step

    def get_step(self) -> int | None:
        self._require_active()
        return self._step


def current_run() -> RunContext | None:
    """Return the context active in the current execution context."""
    return _CURRENT.get()


def execute(draft: Any, argv: Sequence[str], *, cwd: str | Path | None = None) -> Any:  # noqa: C901, PLR0912, PLR0915
    """Own a foreground subprocess, capture its native log, and publish once."""
    if not argv or any(not isinstance(value, str) for value in argv):
        raise ValueError("execute requires a nonempty sequence of command arguments")
    execution: dict[str, Any] = {"argv": list(argv), "observed_by": "cli"}
    boundary = _begin(draft, execution)
    environment = {
        **os.environ,
        "CHERRIES_RUN_ID": draft.id,
        "CHERRIES_RUN_DIR": str(Path(draft.directory).resolve()),
        "CHERRIES_STORE": str(Path(draft.project.store.root).resolve()),
        "CHERRIES_PROJECT": draft.project.id,
    }
    process: subprocess.Popen | None = None
    original_error: BaseException | None = None
    try:
        with (Path(draft.directory) / "run.log").open("ab") as log:
            try:
                process = subprocess.Popen(
                    list(argv),
                    cwd=cwd or draft.project.repository,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                assert process.stdout is not None
                with process.stdout:
                    for block in iter(lambda: process.stdout.read1(64 * 1024), b""):
                        log.write(block)
                        log.flush()
                        os.fsync(log.fileno())
                        try:
                            console = getattr(sys.stderr, "buffer", None)
                            if console is None:
                                sys.stderr.write(block.decode(errors="replace"))
                                sys.stderr.flush()
                            else:
                                console.write(block)
                                console.flush()
                        except BrokenPipeError:
                            pass
                exit_code = process.wait()
                status = (
                    "succeeded"
                    if exit_code == 0
                    else "cancelled"
                    if exit_code < 0
                    else "failed"
                )
            except BaseException as error:  # noqa: BLE001 - save diagnostics for cancellation and launch failures.
                original_error = error
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                status, exit_code = _exception_status(error)
                if isinstance(error, OSError):
                    exit_code = 127
                log.write(("\n" + "".join(traceback.format_exception(error))).encode())
            finally:
                log.flush()
                os.fsync(log.fileno())
        execution.update(status=status, exit_code=exit_code)
        if original_error is not None:
            execution["exception"] = {
                "type": type(original_error).__qualname__,
                "message": str(original_error),
            }
        if (
            status != "succeeded"
            and _settings(draft.project).get("on_error", "keep") == "discard"
        ):
            shutil.rmtree(draft.directory)
            fsync_dir(draft.directory.parent)
            result = draft._result(  # noqa: SLF001 - persistence result factory
                execution_status=status,
                exit_code=exit_code,
                durability="confirmed",
                discarded=True,
                warnings=["unpublished run discarded by on_error policy"],
            )
        else:
            result = _finish(draft, execution, boundary)
    except BaseException as recording_error:
        result = _failure_result(draft, execution, recording_error)
        if original_error is not None:
            _attach_recording_error(original_error, recording_error, result)
            raise original_error from recording_error
        raise
    if original_error is not None and not isinstance(original_error, OSError):
        with contextlib.suppress(AttributeError, TypeError):
            original_error.run_result = result
        raise original_error
    return result

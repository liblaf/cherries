# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003
"""Ordinary files, safe YAML, reflinks, and Pydantic-validated run metadata."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

ARTIFACT_ROLES = ("inputs", "outputs", "figs")
_last_uuid = 0


def _check_timestamp(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S%z")
    if parsed.isoformat(sep=" ", timespec="seconds") != value:
        raise ValueError("Invalid timestamp: expected YYYY-mm-dd HH:MM:SS±HH:MM")
    return value


class ArtifactEntry(BaseModel):
    """One recorded artifact entry inside run.yaml.artifacts."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or value == "."
            or "\\" in value
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != value
        ):
            raise ValueError(f"Invalid artifact name: {value}")
        return value


class Artifacts(BaseModel):
    """Input, output, and figure artifact manifests for a run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    inputs: list[ArtifactEntry]
    outputs: list[ArtifactEntry]
    figs: list[ArtifactEntry]

    @field_validator("inputs", "outputs", "figs")
    @classmethod
    def _unique_non_conflicting(
        cls, entries: list[ArtifactEntry]
    ) -> list[ArtifactEntry]:
        names = [entry.name for entry in entries]
        name_set = set(names)
        if len(names) != len(name_set):
            raise ValueError("Duplicate artifact name")
        for name in names:
            if any(
                parent.as_posix() in name_set for parent in PurePosixPath(name).parents
            ):
                raise ValueError(f"Artifact file/directory conflict: {name}")
        return entries


class RunMeta(BaseModel):
    """Schema for run.yaml."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(alias="project-id")
    run_id: str = Field(alias="run-id")
    run_name: str = Field(alias="run-name")
    description: str | None = None
    start_time: str = Field(alias="start-time")
    end_time: str | None = Field(alias="end-time")
    tags: list[str]
    params: dict[str, Any]
    commit: str | None = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    metadata: dict[str, Any]
    artifacts: Artifacts

    @field_validator("start_time", "end_time")
    @classmethod
    def _valid_timestamp(cls, value: str | None) -> str | None:
        return None if value is None else _check_timestamp(value)


def now() -> str:
    """Return local wall time at second precision, including its UTC offset."""
    return datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")


def run_relative_path(run_id: str, start_time: str) -> Path:
    """Partition a run by its recorded local start date, without conversion."""
    _check_timestamp(start_time)
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError(f"Invalid run ID: {run_id}")
    return Path(start_time[:4], start_time[5:7], start_time[8:10], run_id)


def uuid7() -> str:
    """Create a time-ordered UUIDv7, including calls in the same millisecond."""
    global _last_uuid  # noqa: PLW0603
    bits = (time.time_ns() // 1_000_000) << 80
    bits |= (uuid.uuid4().int & ((1 << 76) - 1)) | (7 << 76)
    bits = (bits & ~(3 << 62)) | (2 << 62)
    _last_uuid = max(bits, _last_uuid + 1)
    return str(uuid.UUID(int=_last_uuid))


def copy(source: Path, destination: Path) -> Path:
    """Copy files independently, omitting empty directories and preferring reflinks."""
    if source.is_dir():
        for child in source.iterdir():
            copy(child, destination / child.name)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=destination.parent, prefix=".cherries-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as original:
            try:
                fcntl.ioctl(output.fileno(), 0x40049409, original.fileno())
            except OSError as error:
                if error.errno not in {
                    errno.EOPNOTSUPP,
                    errno.ENOTTY,
                    errno.EXDEV,
                    errno.EINVAL,
                    errno.ENOSYS,
                    errno.EBADF,
                }:
                    raise
                shutil.copyfileobj(original, output)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def load_yaml(text: str, source: str | Path = "<yaml>") -> dict[str, Any]:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise TypeError(f"Expected a YAML mapping in {source}")
    return data


def read_yaml(path: Path) -> dict[str, Any]:
    return load_yaml(path.read_text(encoding="utf-8"), path)


def write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    atomic_bytes(
        path,
        yaml.safe_dump(
            dict(data), allow_unicode=True, sort_keys=False, indent=2
        ).encode("utf-8"),
    )


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".cherries-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def identity(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return digest, path.stat().st_size


def empty_artifacts() -> dict[str, list[dict[str, Any]]]:
    return {role: [] for role in ARTIFACT_ROLES}


def collect_artifacts(source: Path, name: str | Path) -> list[dict[str, Any]]:
    """Describe saved files under a declaration, flattening directories."""
    if not source.exists():
        return []
    files = (
        [
            (Path(name) / f.relative_to(source), f)
            for f in sorted(source.rglob("*"))
            if f.is_file()
        ]
        if source.is_dir()
        else [(Path(name), source)]
    )
    return [
        {"name": rel.as_posix(), "sha256": digest, "size": size}
        for rel, file in files
        for digest, size in (identity(file),)
    ]


def validate_metadata(
    data: Mapping[str, Any],
    *,
    expected_run_id: str | None = None,
    unfinished: bool = False,
) -> dict[Path, ArtifactEntry]:
    """Validate run.yaml with Pydantic and return {role/name: ArtifactEntry}."""
    if not isinstance(data, Mapping):
        raise TypeError("run.yaml must be a YAML mapping")
    if "description" in data and data["description"] is None:
        raise ValueError("description must be a string or omitted")
    meta = RunMeta.model_validate(data)
    if expected_run_id is not None and meta.run_id != expected_run_id:
        raise ValueError(f"Run ID mismatch: expected {expected_run_id}")
    if not unfinished and meta.end_time is None:
        raise ValueError("Completed run has no end-time")
    if not unfinished and meta.commit is None:
        raise ValueError("Completed run has no Git commit")
    return {
        Path(role) / entry.name: entry
        for role in ARTIFACT_ROLES
        for entry in getattr(meta.artifacts, role)
    }


def mutable(path: str | Path) -> bool:
    parts = Path(path).parts
    return (len(parts) >= 2 and parts[0] in {"figs", "assets", "reports"}) or str(
        path
    ) in {"README.md", "README.html"}

# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003
"""Ordinary files, safe YAML and content-addressed artifact manifests."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ARTIFACT_ROLES = ("inputs", "outputs", "figs")
DATA_DIRS = set(ARTIFACT_ROLES)
FIELDS = {
    "project-id",
    "run-id",
    "run-name",
    "start-time",
    "end-time",
    "tags",
    "params",
    "commit",
    "metadata",
    "artifacts",
}
_last_uuid = 0


def now() -> str:
    """Return local wall time at second precision, including its UTC offset."""
    return datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")


def run_relative_path(run_id: str, start_time: str) -> Path:
    """Partition a run by its recorded local start date, without conversion."""
    started = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S%z")
    if started.isoformat(sep=" ", timespec="seconds") != start_time:
        raise ValueError("Invalid start-time: expected YYYY-mm-dd HH:MM:SS±HH:MM")
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


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    atomic_bytes(
        path,
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            indent=2,
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


def artifact_record(name: str | Path, source: Path) -> dict[str, Any]:
    digest, size = identity(source)
    return {"name": Path(name).as_posix(), "sha256": digest, "size": size}


def collect_artifacts(source: Path, name: str | Path) -> list[dict[str, Any]]:
    """Describe the saved files under a declaration, flattening directories."""
    if not source.exists():
        return []  # Copying a wholly empty directory creates no destination.
    if source.is_dir():
        return [
            artifact_record(Path(name) / file.relative_to(source), file)
            for file in sorted(source.rglob("*"))
            if file.is_file()
        ]
    return [artifact_record(name, source)]


def artifact_entries(metadata: Mapping[str, Any]) -> dict[Path, dict[str, Any]]:  # noqa: C901 - validate the authoritative manifest before traversal or GC
    """Read and validate logical file identities without opening payloads."""
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != DATA_DIRS:
        raise ValueError("Expected artifacts inputs, outputs and figs lists")
    result = {}
    for role in ARTIFACT_ROLES:
        rows = artifacts[role]
        if not isinstance(rows, list):
            raise ValueError(f"Expected artifacts.{role} list")  # noqa: TRY004 - schema validation consistently raises ValueError
        names = set()
        for entry in rows:
            if not isinstance(entry, dict) or set(entry) != {"name", "sha256", "size"}:
                raise ValueError(f"Invalid artifacts.{role} entry")
            name = entry["name"]
            if not isinstance(name, str) or not name:
                raise ValueError(f"Invalid artifacts.{role} name")
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or path.as_posix() != name
                or name == "."
                or name in names
            ):
                raise ValueError(f"Invalid or duplicate artifacts.{role} name: {name}")
            if (
                not isinstance(entry["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
            ):
                raise ValueError(f"Invalid artifact SHA-256: {name}")
            if type(entry["size"]) is not int or entry["size"] < 0:
                raise ValueError(f"Invalid artifact size: {name}")
            names.add(name)
            result[Path(role) / name] = entry
        for name in names:
            if any(
                parent.as_posix() in names for parent in PurePosixPath(name).parents
            ):
                raise ValueError(f"Artifact file/directory conflict: {role}/{name}")
    return result


def mutable(path: str | Path) -> bool:
    parts = Path(path).parts
    return parts[0] in {"figs", "assets", "reports"} or str(path) in {
        "README.md",
        "README.html",
    }

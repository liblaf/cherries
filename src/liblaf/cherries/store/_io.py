# Copyright (c) 2026 liblaf
"""Small filesystem primitives for the project/run store format."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class StoreError(RuntimeError):
    """An operation cannot satisfy the store contract."""


class IntegrityError(StoreError):
    """Stored bytes or references do not match their declared identity."""


class NotFoundError(StoreError):
    """A requested project, run, or object is missing."""


class ConflictError(StoreError):
    """A mutation conflicts with an existing identity or dependency."""


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _UniqueLoader, node: Any, deep: bool = False) -> dict:  # noqa: FBT001, FBT002 - PyYAML constructor signature
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            msg = f"duplicate YAML key: {key!r}"
            raise IntegrityError(msg)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
_uuid_state = [-1, 0]


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def process_identity(pid: int | None = None) -> dict[str, Any] | None:
    """Identify a Linux process without confusing recycled PIDs or reboots."""
    pid = os.getpid() if pid is None else pid
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "pid": pid,
            "start": fields[19],
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        }
    except (FileNotFoundError, ProcessLookupError):
        return None


def owner_alive(owner: Any) -> bool:
    return (
        isinstance(owner, dict)
        and isinstance(owner.get("pid"), int)
        and process_identity(owner["pid"]) == owner
    )


def uuid7() -> str:
    """Generate time-ordered RFC 9562 UUIDs on Python 3.12 and newer."""
    stamp = max(time.time_ns() // 1_000_000, _uuid_state[0])
    if stamp == _uuid_state[0]:
        _uuid_state[1] += 1
        if _uuid_state[1] >= 1 << 74:
            stamp += 1
            _uuid_state[1] = secrets.randbits(74)
    else:
        _uuid_state[1] = secrets.randbits(74)
    _uuid_state[0] = stamp
    value = (stamp << 80) | (7 << 76) | ((_uuid_state[1] >> 62) << 64)
    value |= (2 << 62) | (_uuid_state[1] & ((1 << 62) - 1))
    return str(uuid.UUID(int=value))


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return "sha256:" + digest.hexdigest(), size


def fingerprint(data: Any) -> str:
    payload = json.dumps(
        data, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    fsync_dir(path.parent)


def read_yaml(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink():
        msg = f"control file is a symbolic link: {path}"
        raise IntegrityError(msg)
    try:
        value = yaml.load(path.read_text(), Loader=_UniqueLoader)  # noqa: S506 - subclass of SafeLoader, rejects duplicate keys
    except yaml.YAMLError as error:
        msg = f"invalid YAML: {path}: {error}"
        raise IntegrityError(msg) from error
    if not isinstance(value, dict):
        msg = f"expected YAML mapping: {path}"
        raise IntegrityError(msg)
    return value


def write_yaml(path: Path, data: Any) -> None:
    atomic_bytes(
        Path(path), yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode()
    )


def relative_path(value: str | Path) -> str:
    text = str(value)
    path = Path(text)
    if (
        not text
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in text
        or "\x00" in text
    ):
        msg = f"expected contained relative path: {value!r}"
        raise IntegrityError(msg)
    normalized = path.as_posix()
    if normalized == ".":
        msg = "empty logical path"
        raise IntegrityError(msg)
    return normalized


def contained(root: Path, relative: str | Path) -> Path:
    root = Path(root).resolve()
    result = root / relative_path(relative)
    if not result.resolve().is_relative_to(root):
        msg = f"path escapes root: {relative}"
        raise IntegrityError(msg)
    for candidate in (result, *result.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            msg = f"symbolic link in store path: {candidate}"
            raise IntegrityError(msg)
    return result


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        msg = f"invalid identifier: {value!r}"
        raise IntegrityError(msg)
    return value


def files(root: Path) -> list[Path]:
    result = []
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            msg = f"symbolic link in stored files: {path}"
            raise IntegrityError(msg)
        if path.is_file():
            result.append(path)
    return result

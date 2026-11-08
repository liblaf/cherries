# Copyright (c) 2026 liblaf
# ruff: noqa: A001, A002, EM101, EM102, SLF001, TRY003
# Public id arguments mirror metadata; store collaborators share the private transaction protocol.
"""Filesystem authority, content storage, and recoverable run mutations."""

from __future__ import annotations

import ast
import contextlib
import copy
import dataclasses
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Self
from urllib.parse import unquote, urlsplit

from ._io import (
    ConflictError,
    IntegrityError,
    NotFoundError,
    StoreError,
    atomic_bytes,
    contained,
    files,
    fingerprint,
    fsync_dir,
    hash_file,
    identifier,
    now,
    owner_alive,
    read_yaml,
    relative_path,
    uuid7,
    write_yaml,
)

_POINTER = re.compile(
    rb"version https://git-lfs.github.com/spec/v1\n"
    rb"oid sha256:([0-9a-f]{64})\nsize (0|[1-9][0-9]*)\n"
)
_OID = re.compile(r"sha256:([0-9a-f]{64})")
_CAS_ROLES = {"inputs", "outputs", "figs"}
_FINAL = {"succeeded", "failed", "cancelled", "recorded"}
_IMMUTABLE = {
    "schema_version",
    "id",
    "project",
    "kind",
    "parameters",
    "execution",
    "git",
    "created_at",
    "started_at",
    "ended_at",
    "status",
    "sources",
    "input_bindings",
    "required_outputs",
    "metrics",
    "parents",
    "source_run",
    "directory_bindings",
}


def parse_pointer(path: Path, *, required: bool = False) -> tuple[str, int] | None:
    """Read the canonical three-line pointer, without guessing from its suffix."""
    with Path(path).open("rb") as stream:
        value = stream.read(1025)
    matched = _POINTER.fullmatch(value)
    if matched:
        return "sha256:" + matched[1].decode(), int(matched[2])
    if required or value.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise IntegrityError(f"invalid LFS pointer: {path}")
    return None


def pointer_bytes(oid: str, size: int) -> bytes:
    _digest(oid)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise IntegrityError(f"invalid object size: {size!r}")
    return (
        f"version https://git-lfs.github.com/spec/v1\noid {oid}\nsize {size}\n"
    ).encode()


def _digest(oid: str) -> str:
    match = _OID.fullmatch(oid)
    if not match:
        raise IntegrityError(f"invalid object identifier: {oid!r}")
    return match[1]


def _copy(source: Path, target: Path) -> None:
    """Install an independent, fsynced regular-file copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with Path(source).open("rb") as reader, temporary.open("wb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.replace(target)
    fsync_dir(target.parent)


def _is_data_pointer(path: str, physical: Path) -> tuple[str, int] | None:
    if _inline(path):
        return None
    return parse_pointer(physical)


def _inline(path: str) -> bool:
    return Path(path).parts[0] not in _CAS_ROLES


def _report_name(name: str) -> str:
    name = relative_path(name)
    if name.startswith(("README", "reports/")):
        return name
    return "reports/" + name


def _bytes_in(directory: Path) -> int:
    return sum(path.stat().st_size for path in files(directory))


def _sync_tree(directory: Path) -> None:
    for path in files(directory):
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    directories = [path for path in directory.rglob("*") if path.is_dir()]
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_dir(path)
    fsync_dir(directory)


def _immutable(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: metadata[key] for key in _IMMUTABLE if key in metadata}


def _input_bindings(metadata: Mapping[str, Any]) -> list[dict]:
    bindings = {item["input"]: item for item in metadata.get("input_bindings", [])}
    for source in metadata.get("sources", []):
        if "input" in source:
            bindings.setdefault(source["input"], source)
    return list(bindings.values())


def _directory_entries(
    source: Path, *, target: Path | None = None
) -> tuple[list[tuple[str, Path]], list[str]]:
    """Resolve imported links while rejecting cycles and overlapping trees."""
    source = source.expanduser().resolve(strict=True)
    if not source.is_dir():
        raise IntegrityError(f"expected a directory: {source}")
    if target is not None:
        destination = target.resolve()
        if source.is_relative_to(destination) or destination.is_relative_to(source):
            raise ConflictError("directory source overlaps its destination")
    members: list[tuple[str, Path]] = []
    empty: list[str] = []

    def visit(
        directory: Path, logical: Path, ancestors: frozenset[tuple[int, int]]
    ) -> None:
        resolved = directory.resolve(strict=True)
        identity = (resolved.stat().st_dev, resolved.stat().st_ino)
        if identity in ancestors:
            raise IntegrityError(f"directory link cycle: {directory}")
        children = sorted(resolved.iterdir())
        if not children:
            empty.append(logical.as_posix())
        for child in children:
            path = logical / child.name
            resolved_child = child.resolve(strict=True)
            if resolved_child.is_dir():
                visit(resolved_child, path, ancestors | {identity})
            elif resolved_child.is_file():
                members.append((path.as_posix(), resolved_child))
            else:
                raise IntegrityError(f"directory member is not a regular file: {child}")

    visit(source, Path(), frozenset())
    return members, empty


def _empty_directories(directory: Path) -> list[str]:
    files(
        directory
    )  # Stored and cached trees must contain ordinary files and directories.
    candidates = [directory, *(path for path in directory.rglob("*") if path.is_dir())]
    return sorted(
        path.relative_to(directory).as_posix()
        for path in candidates
        if not any(path.iterdir())
    )


def _copy_empty_directories(source: Path, destination: Path) -> None:
    for logical in _empty_directories(source):
        target = destination if logical == "." else contained(destination, logical)
        target.mkdir(parents=True, exist_ok=True)


def _check_copy_destination(store: Store, destination: Path) -> None:
    if destination.is_relative_to(store.root):
        raise ConflictError("copy destination is inside an authoritative store")
    for parent in (destination, *destination.parents):
        marker = parent / "store.yaml"
        if marker.is_file() and read_yaml(marker).get("format") == "cherries-run-store":
            raise ConflictError("copy destination is inside an authoritative store")


def _directory_bindings(metadata: Mapping[str, Any]) -> list[dict]:
    return metadata.get("directory_bindings", [])


class Result(dict):
    """A JSON-compatible maintenance receipt with attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


@dataclasses.dataclass(frozen=True)
class FileRef:
    """The exact source bytes offered to a consuming run."""

    project: str
    run: str
    path: str
    oid: str
    size: int
    code_commit: str | None
    bound_at: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class DirectoryRef:
    """An exact directory tree expressed through pinned ordinary file identities."""

    project: str
    run: str
    path: str
    members: tuple[FileRef, ...]
    empty_directories: tuple[str, ...]
    code_commit: str | None = None
    bound_at: str = dataclasses.field(default_factory=now)

    def __post_init__(self) -> None:
        identifier(self.project)
        identifier(self.run)
        relative_path(self.path)
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(self, "empty_directories", tuple(self.empty_directories))
        if not self.members and not self.empty_directories:
            object.__setattr__(self, "empty_directories", (self.path,))
        seen: set[str] = set()
        for member in self.members:
            path = relative_path(member.path)
            if (
                path == self.path
                or not Path(path).is_relative_to(self.path)
                or path in seen
            ):
                raise IntegrityError(f"invalid directory reference member: {path}")
            if (member.project, member.run, member.code_commit) != (
                self.project,
                self.run,
                self.code_commit,
            ):
                raise IntegrityError(
                    "directory reference members have different source identities"
                )
            seen.add(path)
        if any(
            parent.as_posix() in seen for path in seen for parent in Path(path).parents
        ):
            raise IntegrityError("directory reference contains overlapping file paths")
        for empty in self.empty_directories:
            path = relative_path(empty)
            if not Path(path).is_relative_to(self.path) or any(
                Path(member).is_relative_to(path) for member in seen
            ):
                raise IntegrityError(f"invalid empty directory reference: {path}")
            if any(
                other != path and Path(other).is_relative_to(path)
                for other in self.empty_directories
            ):
                raise IntegrityError(
                    f"empty directory contains another directory: {path}"
                )

    @property
    def tree_fingerprint(self) -> str:
        """Identify cache contents without inventing a CAS directory object."""
        return fingerprint(
            {
                "files": sorted(
                    (
                        Path(item.path).relative_to(self.path).as_posix(),
                        item.oid,
                        item.size,
                    )
                    for item in self.members
                ),
                "empty_directories": sorted(
                    Path(path).relative_to(self.path).as_posix()
                    for path in self.empty_directories
                ),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "run": self.run,
            "path": self.path,
            "members": [member.to_dict() for member in self.members],
            "empty_directories": list(self.empty_directories),
            "code_commit": self.code_commit,
            "bound_at": self.bound_at,
        }


@dataclasses.dataclass
class RunResult:
    """Separate process outcome, publication, and durability confirmation."""

    run_id: str
    directory: Path
    execution_status: str
    exit_code: int | None
    saved: bool
    published: bool
    durability: str = "confirmed"
    warnings: list[str] = dataclasses.field(default_factory=list)
    discarded: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = dataclasses.asdict(self)
        result["directory"] = str(self.directory)
        return result


class Store:
    """One explicitly initialized store sharing a CAS across its projects."""

    def __init__(
        self, root: Path, metadata: dict, cache_root: Path | None = None
    ) -> None:
        self.root = root
        self.metadata = metadata
        self.id = metadata["id"]
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.cache_root = (
            Path(cache_root).expanduser().resolve()
            if cache_root is not None
            else base / "cherries" / self.id
        )
        self.projects = Projects(self)
        self.index = Index(self)

    @classmethod
    def open(cls, path: str | Path, *, cache_root: Path | None = None) -> Store:
        root = Path(path).expanduser().resolve()
        marker = root / "store.yaml"
        if marker.exists() and (root / "collection.json").exists():
            raise IntegrityError(f"mixed legacy and project/run store markers: {root}")
        if not marker.is_file():
            if any(
                (root / name).exists()
                for name in ("collection.json", "records", "metadata", "events")
            ):
                raise IntegrityError(f"legacy collection is not a run store: {root}")
            raise NotFoundError(f"store.yaml not found: {root}")
        metadata = read_yaml(marker)
        if (
            metadata.get("format") != "cherries-run-store"
            or metadata.get("format_version") != 1
        ):
            raise IntegrityError(f"unsupported store format: {root}")
        if not isinstance(metadata.get("id"), str):
            raise IntegrityError("store ID is missing")
        identifier(metadata["id"])
        for name in ("projects", "objects"):
            if (root / name).is_symlink():
                raise IntegrityError(f"linked store directory: {root / name}")
        return cls(root, metadata, cache_root)

    @classmethod
    def create(cls, path: str | Path, *, cache_root: Path | None = None) -> Store:
        root = Path(path).expanduser().resolve()
        if root.exists() and any(root.iterdir()):
            raise ConflictError(
                f"store initialization requires an empty directory: {root}"
            )
        root.mkdir(parents=True, exist_ok=True)
        for name in (
            "projects",
            "objects/sha256",
            ".cherries/transactions",
            ".cherries/deletions",
            ".cherries/trash",
        ):
            (root / name).mkdir(parents=True, exist_ok=True)
        write_yaml(
            root / "store.yaml",
            {
                "format": "cherries-run-store",
                "format_version": 1,
                "id": uuid7(),
                "created_at": now(),
            },
        )
        fsync_dir(root)
        return cls.open(root, cache_root=cache_root)

    def _transactions(self) -> list[Path]:
        root = self.root / ".cherries/transactions"
        return sorted(root.iterdir()) if root.exists() else []

    def _writable(self, *, own: Path | None = None) -> None:
        pending = [path for path in self._transactions() if path != own]
        if pending:
            raise ConflictError(
                f"store recovery is required before mutation: {pending[0]}"
            )

    def _transaction(self, kind: str, **fields: Any) -> Path:
        self._writable()
        directory = self.root / ".cherries/transactions" / uuid7()
        directory.mkdir(parents=True)
        write_yaml(
            directory / "journal.yaml", {"kind": kind, "phase": "prepared", **fields}
        )
        fsync_dir(directory.parent)
        return directory

    def object_path(
        self, oid: str, *, verify: bool = True, size: int | None = None
    ) -> Path:
        digest = _digest(oid)
        directory = contained(self.root, f"objects/sha256/{digest[:2]}/{digest[2:4]}")
        candidates = [
            path
            for path in directory.glob(digest + ".*")
            if not path.name.endswith(".tmp")
        ]
        if not candidates:
            raise NotFoundError(f"CAS object is unavailable: {oid}")
        if (
            len(candidates) != 1
            or candidates[0].is_symlink()
            or not candidates[0].is_file()
        ):
            raise IntegrityError(f"noncanonical CAS object: {oid}")
        result = candidates[0]
        if verify:
            actual_oid, actual_size = hash_file(result)
            if actual_oid != oid or (size is not None and actual_size != size):
                raise IntegrityError(f"CAS bytes do not match {oid}: {result}")
        elif size is not None and result.stat().st_size != size:
            raise IntegrityError(f"CAS size does not match {oid}")
        return result

    def put(
        self,
        source: str | Path,
        *,
        suffix: str | None = None,
        logical_path: str | None = None,
    ) -> Result:
        self._writable()
        return self._put(Path(source), suffix=suffix, logical_path=logical_path)

    def _put(
        self,
        source: Path,
        *,
        suffix: str | None = None,
        logical_path: str | None = None,
        rename_existing: bool = True,
        interpret_pointer: bool = True,
    ) -> Result:
        source = source.resolve(strict=True)
        if not source.is_file():
            raise IntegrityError(f"CAS import requires a regular file: {source}")
        pointer = parse_pointer(source) if interpret_pointer else None
        if pointer:
            oid, size = pointer
            return Result(oid=oid, size=size, path=self.object_path(oid, size=size))
        oid, size = hash_file(source)
        digest = _digest(oid)
        extension = (
            suffix
            if suffix is not None
            else Path(logical_path or source.name).suffix.lstrip(".")
        )
        extension = extension.lower().lstrip(".") or "bin"
        if not re.fullmatch(r"[a-z0-9][a-z0-9._+-]*", extension) or extension.endswith(
            ".tmp"
        ):
            raise IntegrityError(f"invalid CAS suffix: {extension!r}")
        target = contained(
            self.root, f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}.{extension}"
        )
        try:
            existing = self.object_path(oid, size=size)
        except NotFoundError:
            existing = None
        if existing is not None:
            if existing != target and rename_existing:
                existing.replace(target)
                fsync_dir(target.parent)
            elif not rename_existing:
                target = existing
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            with source.open("rb") as reader, temporary.open("wb") as writer:
                shutil.copyfileobj(reader, writer, 1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            if hash_file(temporary) != (oid, size):
                raise IntegrityError(f"CAS import changed while copying: {source}")
            temporary.replace(target)
            fsync_dir(target.parent)
            fsync_dir(target.parent.parent)
            fsync_dir(target.parent.parent.parent)
        return Result(oid=oid, size=size, path=target)

    def bind_input(  # noqa: C901 - dispatch preserves file, directory and post-hoc binding semantics
        self,
        draft: Run,
        source: str | Path | FileRef | DirectoryRef,
        logical_path: str,
        *,
        consumed: bool = True,
    ) -> Path:
        self._writable()
        logical_path = relative_path(logical_path)
        if not logical_path.startswith("inputs/"):
            raise IntegrityError("bound execution input must be below inputs/")
        if not isinstance(draft, DraftRun):
            if consumed:
                raise ConflictError(
                    "execution inputs cannot be added after publication"
                )
            with draft.edit() as edit:
                edit.add_file(source, path=logical_path)
            return draft.file(logical_path).materialize()
        if isinstance(source, DirectoryRef) or (
            not isinstance(source, FileRef) and Path(source).expanduser().is_dir()
        ):
            return self._bind_directory(draft, source, logical_path, consumed=consumed)
        target = contained(draft.directory, logical_path)
        bindings = draft.metadata.setdefault("input_bindings", [])
        if any(
            Path(logical_path).is_relative_to(item["input"])
            or Path(item["input"]).is_relative_to(logical_path)
            for item in _directory_bindings(draft.metadata)
        ):
            raise ConflictError(f"input overlaps a bound directory: {logical_path}")
        if any(item["input"] == logical_path for item in bindings):
            raise ConflictError(f"input is already bound: {logical_path}")
        if target.exists() or target.with_name(target.name + ".lfs").exists():
            raise ConflictError(f"input path already exists: {logical_path}")
        if isinstance(source, FileRef):
            relative_path(source.path)
            parent = self.projects.get(source.project).runs.get(source.run)
            if (
                isinstance(parent, DraftRun)
                or parent.metadata.get("git", {}).get("commit") != source.code_commit
            ):
                raise IntegrityError(
                    "input reference does not match a published source identity"
                )
            payload = self.object_path(source.oid, size=source.size)
            binding = {"input": logical_path, **source.to_dict(), "consumed": consumed}
        else:
            original = Path(source).expanduser().resolve(strict=True)
            stored = self._put(original, logical_path=logical_path)
            payload = stored["path"]
            binding = {
                "input": logical_path,
                "oid": stored["oid"],
                "size": stored["size"],
                "original_path": str(original),
                "bound_at": now(),
                "consumed": consumed,
            }
        # Register identity before the path can be handed to the consumer.
        bindings.append(binding)
        if isinstance(source, FileRef):
            draft.metadata.setdefault("sources", []).append(
                {key: value for key, value in binding.items() if key != "consumed"}
            )
        draft._persist()
        _copy(payload, target)
        return target

    def _bind_directory(  # noqa: C901 - register both local and pinned trees before materialization
        self,
        draft: DraftRun,
        source: str | Path | DirectoryRef,
        logical_path: str,
        *,
        consumed: bool,
    ) -> Path:
        target = contained(draft.directory, logical_path)
        if target.exists() or target.with_name(target.name + ".lfs").exists():
            raise ConflictError(f"input path already exists: {logical_path}")
        if any(
            Path(item["input"]).is_relative_to(logical_path)
            or Path(logical_path).is_relative_to(item["input"])
            for item in [
                *_input_bindings(draft.metadata),
                *_directory_bindings(draft.metadata),
            ]
        ):
            raise ConflictError(
                f"directory input overlaps an existing input binding: {logical_path}"
            )
        stamp = now()
        bindings: list[dict] = []
        source_identity = None
        if isinstance(source, DirectoryRef):
            parent = self.projects.get(source.project).runs.get(source.run)
            if (
                isinstance(parent, DraftRun)
                or parent.metadata.get("git", {}).get("commit") != source.code_commit
            ):
                raise IntegrityError(
                    "directory reference does not match a published source identity"
                )
            source_identity = {
                key: getattr(source, key)
                for key in ("project", "run", "path", "code_commit", "bound_at")
            }
            for member in source.members:
                logical = (
                    Path(logical_path) / Path(member.path).relative_to(source.path)
                ).as_posix()
                self.object_path(member.oid, size=member.size)
                bindings.append(
                    {"input": logical, **member.to_dict(), "consumed": consumed}
                )
            empty = [
                (Path(logical_path) / Path(path).relative_to(source.path)).as_posix()
                for path in source.empty_directories
            ]
        else:
            original = Path(source).expanduser().resolve(strict=True)
            members, directories = _directory_entries(original, target=target)
            for relative, physical in members:
                logical = (Path(logical_path) / relative).as_posix()
                stored = self._put(physical, logical_path=logical)
                bindings.append(
                    {
                        "input": logical,
                        "oid": stored["oid"],
                        "size": stored["size"],
                        "original_path": str(original / relative),
                        "bound_at": stamp,
                        "consumed": consumed,
                    }
                )
            empty = [(Path(logical_path) / path).as_posix() for path in directories]
        if not bindings and not empty:
            empty = [logical_path]
        members = [item["input"] for item in bindings]
        binding = {
            "input": logical_path,
            "members": members,
            "empty_directories": empty,
            "consumed": consumed,
            "bound_at": stamp,
        }
        if source_identity is not None:
            binding["source"] = source_identity
            draft.metadata.setdefault("sources", []).extend(
                {key: value for key, value in item.items() if key != "consumed"}
                for item in bindings
            )
        draft.metadata.setdefault("input_bindings", []).extend(bindings)
        draft.metadata.setdefault("directory_bindings", []).append(binding)
        draft.metadata.setdefault("file_groups", []).append(
            {"path": logical_path, "files": members, "empty_directories": empty}
        )
        # Persist the entire offered tree before returning any path to its consumer.
        draft._persist()
        target.mkdir(parents=True)
        for item in bindings:
            payload = self.object_path(item["oid"], size=item["size"])
            _copy(payload, contained(draft.directory, item["input"]))
        for directory in empty:
            contained(draft.directory, directory).mkdir(parents=True, exist_ok=True)
        _sync_tree(target)
        fsync_dir(target.parent)
        return target

    def query(self, **kwargs: Any) -> list[Result]:
        return self.index.query(**kwargs)

    def delete(
        self, selection: Iterable[tuple[str, str]], *, dry_run: bool = True
    ) -> Result:
        """Delete one complete selection, including cross-project dependencies."""
        return _delete_runs(self, set(selection), dry_run=dry_run)

    def copy_runs(
        self,
        runs: Iterable[Run],
        target_store: Store | str | Path,
        *,
        replace: bool = False,
        expected_target: str | dict | None = None,
    ) -> Result:
        """Preflight and copy a complete selected source closure."""
        return _copy_runs(
            list(runs), target_store, replace=replace, expected_target=expected_target
        )

    def verify(
        self, *, objects: bool = False, metadata: bool = True, **_: Any
    ) -> Result:
        errors: list[str] = []
        count = 0
        for project in self.projects:
            for run in project.runs:
                count += 1
                try:
                    run.validate(objects=objects)
                except (StoreError, OSError, ValueError) as error:
                    errors.append(f"{project.id}/{run.id}: {error}")
        if objects:
            try:
                for path in self._objects():
                    match = re.fullmatch(r"([0-9a-f]{64})\.(.+)", path.name)
                    if match is None:
                        raise IntegrityError(f"unknown CAS material: {path}")
                    self.object_path("sha256:" + match[1])
            except (StoreError, OSError) as error:
                errors.append(str(error))
        return Result(
            ok=not errors, runs=count, errors=errors, objects=objects, metadata=metadata
        )

    def _objects(self) -> list[Path]:
        return files(self.root / "objects/sha256")

    def _references(self, *, allow_drafts: bool = False) -> set[str]:  # noqa: C901 - all authoritative roots are checked before reclamation
        self._writable()
        known_root = {"store.yaml", "objects", "projects", ".cherries"}
        unknown_root = [
            path for path in self.root.iterdir() if path.name not in known_root
        ]
        if unknown_root:
            raise ConflictError(
                f"unknown store material requires review: {unknown_root[0]}"
            )
        preservation = self.root / ".cherries/preservation"
        trash = self.root / ".cherries/trash"
        if trash.exists() and any(trash.iterdir()):
            message = f"unreviewed trash requires explicit recovery before GC: {trash}"
            raise ConflictError(message)
        known = {"transactions", "deletions", "trash", "preservation", "write.lock"}
        unknown = [
            path
            for path in (self.root / ".cherries").iterdir()
            if path.name not in known
        ]
        if unknown:
            raise ConflictError(
                f"unknown protected material requires review: {unknown[0]}"
            )
        refs: set[str] = set()
        for project in self.projects:
            for run in project.runs:
                if isinstance(run, DraftRun) and not allow_drafts:
                    raise ConflictError(
                        f"unpublished run requires recovery before GC: {run.directory}"
                    )
                run.validate(objects=False)
                refs.update(
                    item.identity()[0] for item in run.files() if item.is_pointer
                )
                refs.update(
                    binding["oid"] for binding in run.metadata.get("input_bindings", [])
                )
                refs.update(
                    binding["oid"] for binding in run.metadata.get("sources", [])
                )
        if preservation.exists():
            for path in files(preservation):
                if path.suffix not in {".yaml", ".yml"}:
                    raise ConflictError(f"unknown preservation material: {path}")
                document = read_yaml(path)
                if document.get("format") != "cherries-preservation" or not isinstance(
                    document.get("objects"), list
                ):
                    raise ConflictError(f"unrecognized preservation manifest: {path}")
                for item in document["objects"]:
                    oid = item if isinstance(item, str) else item["oid"]
                    self.object_path(oid, verify=False)
                    refs.add(oid)
        return refs

    def gc(self, *, dry_run: bool = True) -> Result:
        refs = self._references()
        garbage: list[Path] = []
        seen: set[str] = set()
        retained_bytes = 0
        for path in self._objects():
            match = re.fullmatch(r"([0-9a-f]{64})\.(.+)", path.name)
            if match is None or path.name.endswith(".tmp"):
                raise ConflictError(f"unfinished or unknown CAS material: {path}")
            oid = "sha256:" + match[1]
            if oid in seen:
                raise IntegrityError(f"multiple canonical paths for {oid}")
            seen.add(oid)
            if oid in refs:
                retained_bytes += path.stat().st_size
            else:
                garbage.append(path)
        reclaimable = sum(path.stat().st_size for path in garbage)
        removed = 0
        if not dry_run:
            for path in garbage:
                size = path.stat().st_size
                path.unlink()
                fsync_dir(path.parent)
                removed += size
        return Result(
            dry_run=dry_run,
            objects=[str(path.relative_to(self.root)) for path in garbage],
            reclaimable_bytes=reclaimable,
            reclaimed_bytes=removed,
            retained_bytes=retained_bytes,
            warnings=[],
        )

    def recover(self, run_id: str | None = None) -> Result:  # noqa: C901, PLR0912 - explicit recovery dispatch preserves unknown journals
        recovered: list[str] = []
        retained: list[str] = []
        warnings: list[str] = []
        metrics_recovery: list[dict] = []
        for transaction in self._transactions():
            try:
                journal = read_yaml(transaction / "journal.yaml")
                if run_id is not None and journal.get("run") != run_id:
                    continue
                kind = journal["kind"]
                if kind == "edit":
                    _recover_edit(self, transaction, journal)
                    recovered.append(str(transaction.name))
                elif kind == "delete":
                    self._finish_delete(transaction, journal)
                    recovered.append(str(transaction.name))
                elif kind == "save":
                    retained_run = _recover_save(self, transaction, journal)
                    if retained_run is not None:
                        retained.append(str(retained_run))
                    recovered.append(transaction.name)
                elif kind == "copy":
                    _recover_copy(self, transaction, journal)
                    recovered.append(transaction.name)
                else:
                    raise IntegrityError(f"unknown transaction kind: {kind}")
            except (StoreError, OSError, KeyError, ValueError) as error:
                warnings.append(f"{transaction}: {error}")
        for project in self.projects:
            for run in project.runs:
                if isinstance(run, DraftRun) and (run_id is None or run.id == run_id):
                    from ._runtime import recover_metrics

                    if run.metadata.get("status") == "running" and owner_alive(
                        run.metadata.get("recording_owner")
                    ):
                        warnings.append(
                            f"running writer must stop before recovery: {run.directory}"
                        )
                        retained.append(str(run.directory))
                        continue
                    try:
                        recovery = recover_metrics(run.directory)
                        if recovery:
                            metrics_recovery.append(recovery)
                    except (StoreError, ValueError, OSError) as error:
                        warnings.append(
                            f"metric recovery requires inspection: {run.directory}: {error}"
                        )
                if (
                    isinstance(run, DraftRun)
                    and (run_id is None or run.id == run_id)
                    and str(run.directory) not in retained
                ):
                    retained.append(str(run.directory))
        return Result(
            recovered=recovered,
            retained=retained,
            warnings=warnings,
            ok=not warnings,
            metrics_recovery=metrics_recovery,
        )

    def _finish_delete(self, transaction: Path, journal: dict) -> None:
        if journal["phase"] == "prepared":
            shutil.rmtree(transaction)
            return
        for item in journal["runs"]:
            project = self.projects.get(item["project"])
            original = contained(project.directory / "runs", item["run"])
            staged = transaction / "trash" / item["project"] / item["run"]
            if original.exists():
                if (
                    Run(project, item["run"], original).fingerprint
                    != item["fingerprint"]
                ):
                    raise ConflictError(f"run changed during deletion: {original}")
                staged.parent.mkdir(parents=True, exist_ok=True)
                original.replace(staged)
                fsync_dir(original.parent)
            _delete_ref(project, item["run"])
        write_yaml(
            self.root / ".cherries/deletions" / f"{transaction.name}.yaml",
            {
                "id": transaction.name,
                "deleted_at": now(),
                "runs": journal["runs"],
            },
        )
        shutil.rmtree(transaction)


class Projects:
    def __init__(self, store: Store) -> None:
        self.store = store

    def __iter__(self) -> Iterator[Project]:
        root = self.store.root / "projects"
        if root.exists():
            for path in sorted(root.iterdir()):
                if path.is_symlink() or not path.is_dir():
                    raise IntegrityError(f"unknown project material: {path}")
                yield self.get(path.name)

    def list(self) -> list[Project]:
        return list(self)

    def add(
        self, id: str, *, repo: str | Path | None = None, name: str | None = None
    ) -> Project:
        self.store._writable()
        id = identifier(id)
        directory = self.store.root / "projects" / id
        if directory.exists():
            project = self.get(id)
            if repo is not None:
                project._bind(Path(repo))
            return project
        directory.mkdir(parents=True)
        (directory / "runs").mkdir()
        archive = directory / f"{id}.git"
        subprocess.run(
            ["git", "init", "--bare", "--quiet", str(archive)],
            check=True,
            capture_output=True,
        )
        write_yaml(
            directory / "project.yaml",
            {
                "schema_version": 1,
                "id": id,
                "name": name or id,
                "created_at": now(),
                "code": {"repository": archive.name},
            },
        )
        project = self.get(id)
        if repo is not None:
            project._bind(Path(repo))
        return project

    def get(self, id: str) -> Project:
        directory = contained(self.store.root / "projects", identifier(id))
        if not (directory / "project.yaml").is_file():
            raise NotFoundError(f"project not found: {id}")
        metadata = read_yaml(directory / "project.yaml")
        if metadata.get("schema_version") != 1 or metadata.get("id") != id:
            raise IntegrityError(f"invalid project metadata: {id}")
        return Project(self.store, id, directory, metadata)


class Project:
    def __init__(self, store: Store, id: str, directory: Path, metadata: dict) -> None:
        self.store, self.id, self.directory, self.metadata = (
            store,
            id,
            directory,
            metadata,
        )
        self.archive = contained(directory, metadata["code"]["repository"])
        self.runs = Runs(self)

    @property
    def repository(self) -> Path:
        path = self.store.cache_root / "repositories.yaml"
        bindings = read_yaml(path) if path.exists() else {}
        if self.id not in bindings:
            raise NotFoundError(f"no local repository binding for project {self.id}")
        return Path(bindings[self.id])

    @repository.setter
    def repository(self, path: str | Path) -> None:
        self._bind(Path(path))

    def with_repository(self, path: str | Path) -> Project:
        self._bind(Path(path))
        return self

    def _bind(self, repository: Path) -> None:
        repository = repository.expanduser().resolve(strict=True)
        process = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        repository = Path(process.stdout.strip()).resolve(strict=True)
        path = self.store.cache_root / "repositories.yaml"
        bindings = read_yaml(path) if path.exists() else {}
        bindings[self.id] = str(repository)
        write_yaml(path, bindings)

    def to_dict(self) -> dict:
        return copy.deepcopy(self.metadata)

    def run(self, **kwargs: Any) -> Any:
        from ._runtime import RunContext

        return RunContext(self, **kwargs)


class Runs:
    def __init__(self, project: Project) -> None:
        self.project = project

    def __iter__(self) -> Iterator[Run]:
        for path in sorted((self.project.directory / "runs").iterdir()):
            if path.is_symlink() or not path.is_dir():
                raise IntegrityError(f"unknown run material: {path}")
            yield self.get(path.name.removesuffix(".tmp"))

    def create(
        self,
        *,
        name: str,
        kind: str = "record",
        parameters: dict | None = None,
        tags: Iterable[str] = (),
        id: str | None = None,
    ) -> DraftRun:
        self.project.store._writable()
        id = identifier(id) if id is not None else uuid7()
        directory = self.project.directory / "runs" / f"{id}.tmp"
        if directory.exists() or directory.with_name(id).exists():
            raise ConflictError(f"run ID already exists: {id}")
        directory.mkdir()
        for role in ("inputs", "outputs", "figs", "assets", "reports", "scratch"):
            (directory / role).mkdir()
        stamp = now()
        metadata = {
            "schema_version": 1,
            "id": id,
            "project": self.project.id,
            "name": name,
            "kind": kind,
            "status": "prepared",
            "created_at": stamp,
            "updated_at": stamp,
            "parameters": parameters or {},
            "tags": sorted(set(tags)),
            "sources": [],
            "input_bindings": [],
            "extensions": {},
        }
        write_yaml(directory / "run.yaml", metadata)
        fsync_dir(directory.parent)
        return DraftRun(self.project, id, directory)

    def get(self, id: str) -> Run:
        id = identifier(id)
        root = self.project.directory / "runs"
        final, draft = contained(root, id), contained(root, id + ".tmp")
        if final.exists() and draft.exists():
            raise IntegrityError(f"both published and draft directories exist: {id}")
        if final.is_dir():
            return Run(self.project, id, final)
        if draft.is_dir():
            return DraftRun(self.project, id, draft)
        raise NotFoundError(f"run not found: {self.project.id}/{id}")

    def query(self, **kwargs: Any) -> list[Result]:
        return self.project.store.index.query(project=self.project.id, **kwargs)

    def draft(self, id: str) -> DraftRun:
        run = self.get(id)
        if not isinstance(run, DraftRun):
            raise ConflictError(f"run is already published: {id}")
        return run

    def delete(self, ids: Iterable[str] | str, *, dry_run: bool = True) -> Result:
        if isinstance(ids, str):
            ids = [ids]
        return self.project.store.delete(
            ((self.project.id, id) for id in ids), dry_run=dry_run
        )


class Run:
    """An authoritative published record and its directly readable reports."""

    def __init__(self, project: Project, id: str, directory: Path) -> None:
        self.project, self.id, self.directory = project, id, directory

    @property
    def store(self) -> Store:
        return self.project.store

    @property
    def metadata(self) -> dict:
        return read_yaml(self.directory / "run.yaml")

    @property
    def metrics(self) -> RunMetrics:
        return RunMetrics(self)

    def to_dict(self) -> dict:
        return self.metadata

    @property
    def fingerprint(self) -> str:
        return fingerprint(
            {
                "files": {
                    path.relative_to(self.directory).as_posix(): hash_file(path)
                    for path in files(self.directory)
                },
                "empty_directories": _empty_directories(self.directory),
            }
        )

    def file(self, path: str) -> RunFile:
        return RunFile(self, relative_path(path))

    def files(self) -> list[RunFile]:
        result: list[RunFile] = []
        raw_inputs = (
            {item["input"] for item in _input_bindings(self.metadata)}
            if isinstance(self, DraftRun)
            else set()
        )
        for path in files(self.directory):
            name = path.relative_to(self.directory).as_posix()
            if name == "run.yaml" or name.startswith("scratch/"):
                continue
            is_pointer = (
                name not in raw_inputs and _is_data_pointer(name, path) is not None
            )
            if (
                name not in raw_inputs
                and name.endswith(".lfs")
                and Path(name).parts[0] in _CAS_ROLES
            ):
                parse_pointer(path, required=True)
            if is_pointer and name.endswith(".lfs"):
                name = name[:-4]
            result.append(RunFile(self, name))
        return result

    def validate(self, *, objects: bool = True) -> Result:  # noqa: C901, PLR0912 - validate independent identity, file, input, source and report evidence
        metadata = self.metadata
        if (
            metadata.get("schema_version") != 1
            or metadata.get("id") != self.id
            or metadata.get("project") != self.project.id
        ):
            raise IntegrityError(f"invalid run identity: {self.directory}")
        if not isinstance(self, DraftRun) and metadata.get("status") not in _FINAL:
            raise IntegrityError(f"published run has incomplete status: {self.id}")
        seen: set[str] = set()
        for item in self.files():
            if item.path in seen:
                raise IntegrityError(f"duplicate logical path: {item.path}")
            seen.add(item.path)
            if item.is_pointer:
                oid, size = item.identity()
                self.store.object_path(oid, size=size, verify=objects)
        for binding in _input_bindings(metadata):
            if not binding.get("consumed", True):
                continue
            path = relative_path(binding["input"])
            if self.file(path).identity() != (binding["oid"], binding["size"]):
                raise IntegrityError(f"consumed input was changed: {path}")
        self._validate_directory_bindings()
        for project, id in _source_edges(self):
            parent = self.store.projects.get(project).runs.get(id)
            if isinstance(parent, DraftRun):
                raise IntegrityError(f"source run is unpublished: {project}/{id}")
        for group in metadata.get("file_groups", []):
            members = [
                *group.get("files", []),
                *([group["main"]] if "main" in group else []),
            ]
            for member in members:
                if not self.file(relative_path(member)).exists():
                    raise IntegrityError(f"required companion is missing: {member}")
            for empty in group.get("empty_directories", []):
                relative_path(empty)
        commit = metadata.get("git", {}).get("commit")
        if commit and _ref_commit(self.project, self.id) != commit:
            raise IntegrityError(
                f"recorded source commit does not match run ref: {self.id}"
            )
        _validate_overlay(self, self.directory, set())
        return Result(ok=True, project=self.project.id, run=self.id, files=len(seen))

    def _validate_directory_bindings(self) -> None:
        for binding in _directory_bindings(self.metadata):
            if not binding.get("consumed", True):
                continue
            members, empty = self.file(binding["input"])._directory_layout()
            if isinstance(self, DraftRun):
                physical = contained(self.directory, binding["input"])
                if not physical.is_dir():
                    raise IntegrityError(
                        f"consumed directory input is missing: {binding['input']}"
                    )
                empty = [
                    (Path(binding["input"]) / path).as_posix()
                    for path in _empty_directories(physical)
                ]
            if {item.path for item in members} != set(binding["members"]) or set(
                empty
            ) != set(binding["empty_directories"]):
                raise IntegrityError(
                    f"consumed directory input was changed: {binding['input']}"
                )

    def edit(self) -> RunEditor:
        if isinstance(self, DraftRun) and self.metadata.get("status") != "prepared":
            raise ConflictError("a running or finalizing draft cannot be edited")
        return RunEditor(self)

    def export(self, destination: str | Path, *, with_data: bool = False) -> Path:
        self.validate(objects=with_data)
        destination = Path(destination).expanduser().resolve()
        _check_copy_destination(self.store, destination)
        if destination.exists() and any(destination.iterdir()):
            raise ConflictError(f"export destination is not empty: {destination}")
        if destination.is_relative_to(self.directory) or self.directory.is_relative_to(
            destination
        ):
            raise ConflictError("export destination overlaps authoritative run")
        destination.mkdir(parents=True, exist_ok=True)
        for path in files(self.directory):
            name = path.relative_to(self.directory).as_posix()
            if with_data and _is_data_pointer(name, path) is not None:
                logical = name.removesuffix(".lfs")
                item = self.file(logical)
                oid, size = item.identity()
                _copy(
                    self.store.object_path(oid, size=size),
                    contained(destination, logical),
                )
            else:
                _copy(path, contained(destination, name))
        for group in self.metadata.get("file_groups", []):
            for name in group.get("empty_directories", []):
                contained(destination, name).mkdir(parents=True, exist_ok=True)
        _copy_empty_directories(self.directory, destination)
        return destination

    def copy_to(
        self,
        target_store: Store | str | Path,
        *,
        replace: bool = False,
        expected_target: str | None = None,
    ) -> Result:
        return _copy_runs(
            [self], target_store, replace=replace, expected_target=expected_target
        )


class DraftRun(Run):
    """An unpublished workspace whose input bindings precede consumption."""

    def __init__(self, project: Project, id: str, directory: Path) -> None:
        super().__init__(project, id, directory)
        self._metadata = read_yaml(directory / "run.yaml")

    @property
    def metadata(self) -> dict:
        return self._metadata

    def _persist(self) -> None:
        write_yaml(self.directory / "run.yaml", self._metadata)

    def _result(
        self,
        *,
        execution_status: str,
        exit_code: int | None,
        saved: bool = False,
        published: bool = False,
        durability: str = "unconfirmed",
        warnings: Iterable[str] = (),
        discarded: bool = False,
    ) -> RunResult:
        return RunResult(
            self.id,
            self.directory,
            execution_status,
            exit_code,
            saved=saved,
            published=published,
            durability=durability,
            warnings=list(warnings),
            discarded=discarded,
        )

    def set_source_run(self, source: Run) -> None:
        self.metadata["source_run"] = {"project": source.project.id, "run": source.id}
        self.metadata.setdefault("parents", []).append(
            {"project": source.project.id, "run": source.id}
        )
        self._persist()

    def input(
        self, source: str | Path | FileRef | DirectoryRef, *, name: str | None = None
    ) -> Path:
        name = name or (
            Path(source.path).name
            if isinstance(source, (FileRef, DirectoryRef))
            else Path(source).name
        )
        return self.store.bind_input(
            self, source, "inputs/" + relative_path(name), consumed=True
        )

    def output(self, name: str, *, required: bool = True) -> Path:
        name = "outputs/" + relative_path(name)
        if required and name not in self.metadata.setdefault("required_outputs", []):
            self.metadata["required_outputs"].append(name)
            self._persist()
        path = contained(self.directory, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def figure(self, name: str, *, required: bool = True) -> Path:
        name = "figs/" + relative_path(name)
        if required and name not in self.metadata.setdefault("required_outputs", []):
            self.metadata["required_outputs"].append(name)
            self._persist()
        path = contained(self.directory, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def scratch(self, name: str) -> Path:
        path = contained(self.directory, "scratch/" + relative_path(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def report(self, name: str) -> Path:
        path = contained(self.directory, _report_name(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def asset(self, name: str, *, source: str | Path) -> Path:
        path = contained(self.directory, "assets/" + relative_path(name))
        _copy(Path(source).resolve(strict=True), path)
        return path

    def add_file(
        self, source: str | Path | FileRef | DirectoryRef, *, path: str
    ) -> Path:
        path = relative_path(path)
        if path.startswith("inputs/"):
            return self.store.bind_input(self, source, path, consumed=False)
        if isinstance(source, DirectoryRef):
            target = contained(self.directory, path)
            _write_directory_reference(self.store, source, target)
            members = [
                (Path(path) / Path(item.path).relative_to(source.path)).as_posix()
                for item in source.members
            ]
            empty = [
                (Path(path) / Path(item).relative_to(source.path)).as_posix()
                for item in source.empty_directories
            ]
            self.metadata.setdefault("file_groups", []).append(
                {"path": path, "files": members, "empty_directories": empty}
            )
            self.metadata.setdefault("attachments", []).append(
                {
                    "path": path,
                    "attached_at": now(),
                    "source": {
                        key: getattr(source, key)
                        for key in ("project", "run", "path", "code_commit", "bound_at")
                    },
                }
            )
            self._persist()
            return target
        if isinstance(source, FileRef):
            payload = self.store.object_path(source.oid, size=source.size)
        else:
            payload = Path(source).expanduser().resolve(strict=True)
            pointer = parse_pointer(payload) if payload.is_file() else None
            if pointer:
                payload = self.store.object_path(pointer[0], size=pointer[1])
        target = contained(self.directory, path)
        if payload.is_dir():
            self._add_directory(payload, target, path)
        else:
            _copy(payload, target)
        return target

    def _add_directory(self, source: Path, target: Path, logical: str) -> None:
        entries, directories = _directory_entries(source, target=target)
        empty = [(Path(logical) / relative).as_posix() for relative in directories]
        members = [(Path(logical) / relative).as_posix() for relative, _ in entries]
        target.mkdir(parents=True, exist_ok=True)
        for relative, physical in entries:
            pointer = parse_pointer(physical)
            payload = (
                self.store.object_path(pointer[0], size=pointer[1])
                if pointer
                else physical
            )
            _copy(payload, contained(target, relative))
        for directory in empty:
            contained(self.directory, directory).mkdir(parents=True, exist_ok=True)
        self.metadata.setdefault("file_groups", []).append(
            {"path": logical, "files": members, "empty_directories": empty}
        )
        self._persist()

    def group(
        self, main: str, *, files: Iterable[str], empty_directories: Iterable[str] = ()
    ) -> None:
        """Declare companions that must be restored together with a main file."""
        main = relative_path(main)
        members = list(dict.fromkeys([main, *(relative_path(path) for path in files)]))
        self.metadata.setdefault("file_groups", []).append(
            {
                "main": main,
                "files": members,
                "empty_directories": [
                    relative_path(path) for path in empty_directories
                ],
            }
        )
        self._persist()

    def execute(
        self, argv: Iterable[str], *, cwd: str | Path | None = None
    ) -> RunResult:
        from ._runtime import execute

        return execute(self, list(argv), cwd=cwd)

    def save(  # noqa: C901, PLR0912, PLR0915 - publication stages preserve explicit failure boundaries
        self,
        *,
        status: str = "recorded",
        execution: dict | None = None,
        git: dict | None = None,
        metrics: dict | None = None,
    ) -> RunResult:
        if status not in _FINAL:
            raise IntegrityError(f"invalid final run status: {status}")
        self.store._writable()
        if not self.directory.name.endswith(".tmp"):
            raise ConflictError("run is already published")
        transaction = self.store._transaction(
            "save", project=self.project.id, run=self.id
        )
        warnings: list[str] = []
        try:
            # Inputs are verified before any original workspace data is removed.
            self._validate_directory_bindings()
            for binding in _input_bindings(self.metadata):
                if binding.get("consumed", True) and self.file(
                    binding["input"]
                ).identity() != (binding["oid"], binding["size"]):
                    raise IntegrityError(
                        f"consumed input was changed: {binding['input']}"
                    )
            missing = [
                name
                for name in self.metadata.get("required_outputs", [])
                if not self.file(name).exists()
            ]
            if missing and status == "succeeded":
                raise IntegrityError(
                    f"required outputs are missing: {', '.join(missing)}"
                )
            if missing:
                self.metadata["missing_outputs"] = missing
            if execution is not None:
                self.metadata["execution"] = execution
            if git is None:
                git = self.metadata.get("git")
                if git is None or not git.get("commit"):
                    from ._source import archive_snapshot, archived_snapshot

                    snapshot = archived_snapshot(self.project, self.id)
                    snapshot = snapshot or archive_snapshot(self.project, self.id)
                    git = {**(git or {}), **snapshot}
                    if git.get("start_fingerprint") and not git.get("end_fingerprint"):
                        git["source_stable"] = None
            if git is not None:
                self.metadata["git"] = git
            if metrics is None and (self.directory / "metrics.jsonl").exists():
                from ._runtime import finalize_metrics

                metrics = finalize_metrics(self.directory)
            if metrics is not None:
                self.metadata["metrics"] = metrics
            self.metadata["status"] = "finalizing"
            self._persist()
            for role in _CAS_ROLES:
                root = self.directory / role
                for source in files(root) if root.exists() else []:
                    logical = source.relative_to(self.directory).as_posix()
                    binding = next(
                        (
                            item
                            for item in self.metadata.get("input_bindings", [])
                            if item["input"] == logical
                        ),
                        None,
                    )
                    parsed = parse_pointer(source) if binding is None else None
                    if parsed and source.name.endswith(".lfs"):
                        self.store.object_path(parsed[0], size=parsed[1])
                        continue
                    if binding is not None and hash_file(source) == (
                        binding["oid"],
                        binding["size"],
                    ):
                        stored = Result(
                            oid=binding["oid"],
                            size=binding["size"],
                            path=self.store.object_path(
                                binding["oid"], size=binding["size"]
                            ),
                        )
                    else:
                        stored = self.store._put(source, logical_path=logical)
                    target = source.with_name(source.name + ".lfs")
                    if target.exists() and parse_pointer(target, required=True) != (
                        stored["oid"],
                        stored["size"],
                    ):
                        raise IntegrityError(f"conflicting file and pointer: {logical}")
                    atomic_bytes(target, pointer_bytes(stored["oid"], stored["size"]))
                    source.unlink()
                    fsync_dir(source.parent)
            self.metadata["status"] = status
            self.metadata["updated_at"] = now()
            self._persist()
            self.validate(objects=True)
            cleanup = transaction / "cleanup"
            cleanup.mkdir()
            for name in ("scratch", "metrics.jsonl"):
                source = self.directory / name
                if source.exists():
                    source.replace(cleanup / name)
                    fsync_dir(self.directory)
            _sync_tree(self.directory)
            destination = self.directory.with_name(self.id)
            self.directory.replace(destination)
            self.directory = destination
            try:
                fsync_dir(destination.parent)
            except OSError as error:
                return RunResult(
                    self.id,
                    destination,
                    status,
                    self.metadata.get("execution", {}).get("exit_code"),
                    saved=False,
                    published=True,
                    durability="unconfirmed",
                    warnings=[str(error)],
                )
        except (OSError, StoreError, ValueError, subprocess.SubprocessError) as error:
            result = RunResult(
                self.id,
                self.directory,
                status,
                self.metadata.get("execution", {}).get("exit_code"),
                saved=False,
                published=False,
            )
            error.result = result
            raise
        try:
            shutil.rmtree(transaction)
        except OSError as error:
            warnings.append(f"temporary cleanup pending: {error}")
        try:
            self.store.index.update(Run(self.project, self.id, self.directory))
        except (OSError, StoreError, sqlite3.Error) as error:
            warnings.append(f"index update failed: {error}")
        return RunResult(
            self.id,
            self.directory,
            status,
            self.metadata.get("execution", {}).get("exit_code"),
            saved=True,
            published=True,
            warnings=warnings,
        )


class RunFile:
    def __init__(self, run: Run, path: str) -> None:
        self.run, self.path = run, path

    @property
    def is_directory(self) -> bool:
        physical = contained(self.run.directory, self.path)
        if physical.is_dir():
            return True
        if (
            physical.exists()
            or contained(self.run.directory, self.path + ".lfs").is_file()
        ):
            return False
        prefix = self.path + "/"
        return any(
            group.get("path") == self.path
            or any(
                path == self.path or path.startswith(prefix)
                for path in group.get("empty_directories", [])
            )
            or any(path.startswith(prefix) for path in group.get("files", []))
            for group in self.run.metadata.get("file_groups", [])
        )

    @property
    def physical_path(self) -> Path:
        plain = contained(self.run.directory, self.path)
        if self.is_directory:
            return plain
        pointer = contained(self.run.directory, self.path + ".lfs")
        if pointer.is_file():
            identity = parse_pointer(pointer, required=True)
            if plain.is_file() and (
                not isinstance(self.run, DraftRun) or hash_file(plain) != identity
            ):
                raise IntegrityError(f"conflicting real file and pointer: {self.path}")
            return pointer
        if plain.is_file():
            return plain
        raise NotFoundError(f"run file not found: {self.run.id}/{self.path}")

    @property
    def is_pointer(self) -> bool:
        if self.is_directory:
            return False
        physical = self.physical_path
        if isinstance(self.run, DraftRun) and physical == contained(
            self.run.directory, self.path
        ):
            return False
        return _is_data_pointer(self.path, physical) is not None

    def exists(self) -> bool:
        try:
            _ = self.physical_path
        except NotFoundError:
            return False
        return True

    def identity(self) -> tuple[str, int]:
        if self.is_directory:
            raise IntegrityError("directories have per-file identities; use ref()")
        path = self.physical_path
        return (
            parse_pointer(path, required=True) if self.is_pointer else hash_file(path)
        )

    def _directory_layout(self) -> tuple[list[RunFile], list[str]]:
        if not self.is_directory:
            raise IntegrityError(
                f"directory is missing or replaced by a file: {self.path}"
            )
        prefix = self.path + "/"
        members = [item for item in self.run.files() if item.path.startswith(prefix)]
        empty: set[str] = set()
        physical = contained(self.run.directory, self.path)
        if physical.is_dir():
            empty.update(
                (Path(self.path) / path).as_posix()
                for path in _empty_directories(physical)
            )
        for group in self.run.metadata.get("file_groups", []):
            empty.update(
                path
                for path in group.get("empty_directories", [])
                if path == self.path or path.startswith(prefix)
            )
        empty = {
            path
            for path in empty
            if not any(item.path.startswith(path + "/") for item in members)
        }
        empty = {
            path
            for path in empty
            if not any(
                other != path and other.startswith(path + "/") for other in empty
            )
        }
        if not members and not empty:
            empty.add(self.path)
        return members, sorted(empty)

    def ref(self) -> FileRef | DirectoryRef:
        stamp = now()
        commit = self.run.metadata.get("git", {}).get("commit")
        if self.is_directory:
            members, empty = self._directory_layout()
            return DirectoryRef(
                self.run.project.id,
                self.run.id,
                self.path,
                tuple(item._file_ref(commit, stamp) for item in members),
                tuple(empty),
                commit,
                stamp,
            )
        return self._file_ref(commit, stamp)

    def _file_ref(self, commit: str | None, stamp: str) -> FileRef:
        oid, size = self.identity()
        # Inline report/asset references need a durable CAS identity too.
        if not self.is_pointer:
            self.run.store._put(
                self.physical_path,
                logical_path=self.path,
                rename_existing=False,
                interpret_pointer=False,
            )
        else:
            self.run.store.object_path(oid, size=size)
        return FileRef(
            self.run.project.id,
            self.run.id,
            self.path,
            oid,
            size,
            commit,
            stamp,
        )

    def materialize(self) -> Path:
        if self.is_directory:
            return self._materialize_directory()
        oid, size = self.identity()
        digest = _digest(oid)
        groups = [
            group
            for group in self.run.metadata.get("file_groups", [])
            if self.path == group.get("main") or self.path in group.get("files", [])
        ]
        cache = self.run.store.cache_root / "files" / digest
        if groups:
            identities = {self.path: (oid, size)}
            empty_directories = set()
            for group in groups:
                for member in group.get("files", []):
                    identities[member] = self.run.file(member).identity()
                empty_directories.update(group.get("empty_directories", []))
            digest = _digest(
                fingerprint(
                    {
                        "files": identities,
                        "empty_directories": sorted(empty_directories),
                    }
                )
            )
            cache = self.run.store.cache_root / "groups" / digest
        target = contained(cache, self.path)
        if (
            not target.is_file()
            or target.is_symlink()
            or hash_file(target) != (oid, size)
        ):
            source = (
                self.run.store.object_path(oid, size=size)
                if self.is_pointer
                else self.physical_path
            )
            _copy(source, target)
        for group in groups:
            members = group.get("files", [])
            for member in members:
                if member != self.path:
                    other = self.run.file(member)
                    source = (
                        other.run.store.object_path(
                            other.identity()[0], size=other.identity()[1]
                        )
                        if other.is_pointer
                        else other.physical_path
                    )
                    _copy(
                        source,
                        contained(cache, member),
                    )
            for empty in group.get("empty_directories", []):
                contained(cache, empty).mkdir(parents=True, exist_ok=True)
        return target

    def _materialize_directory(self) -> Path:
        reference = self.ref()
        if not isinstance(reference, DirectoryRef):
            raise IntegrityError("directory changed while fixing its identity")
        base = (
            self.run.store.cache_root
            / "directories"
            / _digest(reference.tree_fingerprint)
        )
        target = contained(base, self.path)
        if _directory_matches(reference, target):
            return target
        temporary = target.with_name(target.name + ".tmp")
        if temporary.exists():
            shutil.rmtree(temporary) if temporary.is_dir() else temporary.unlink()
        _write_directory_reference(self.run.store, reference, temporary)
        _sync_tree(temporary)
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        temporary.replace(target)
        fsync_dir(target.parent)
        return target

    def copy_to(self, destination: str | Path) -> Path:  # noqa: C901 - file companions and exact directory trees use distinct layouts
        destination = Path(destination).expanduser().resolve()
        _check_copy_destination(self.run.store, destination)
        if self.is_directory:
            if destination.is_relative_to(
                self.run.store.root
            ) or self.run.directory.is_relative_to(destination):
                raise ConflictError("directory copy overlaps authoritative store bytes")
            if destination.exists() and (
                not destination.is_dir() or any(destination.iterdir())
            ):
                raise ConflictError(
                    f"directory copy destination is not empty: {destination}"
                )
            reference = self.ref()
            if not isinstance(reference, DirectoryRef):
                raise IntegrityError("directory changed while fixing its identity")
            _write_directory_reference(self.run.store, reference, destination)
            return destination
        if destination.is_dir():
            destination /= Path(self.path).name
        _check_copy_destination(self.run.store, destination)
        oid, size = self.identity()
        source = (
            self.run.store.object_path(oid, size=size)
            if self.is_pointer
            else self.physical_path
        )
        _copy(source, destination)
        for group in self.run.metadata.get("file_groups", []):
            members = group.get("files", [])
            if self.path != group.get("main") and self.path not in members:
                continue
            base = Path(self.path).parent
            for member in members:
                if member == self.path:
                    continue
                if not Path(member).is_relative_to(base):
                    raise IntegrityError(
                        "companions outside the main directory require run export"
                    )
                item = self.run.file(member)
                member_oid, member_size = item.identity()
                payload = (
                    self.run.store.object_path(member_oid, size=member_size)
                    if item.is_pointer
                    else item.physical_path
                )
                _copy(
                    payload,
                    contained(destination.parent, Path(member).relative_to(base)),
                )
            for empty in group.get("empty_directories", []):
                if Path(empty).is_relative_to(base):
                    contained(destination.parent, Path(empty).relative_to(base)).mkdir(
                        parents=True, exist_ok=True
                    )
        return destination

    def to_dict(self) -> dict:
        if self.is_directory:
            members, empty = self._directory_layout()
            return {
                "path": self.path,
                "directory": True,
                "files": [item.to_dict() for item in members],
                "empty_directories": empty,
                "size": sum(item.identity()[1] for item in members),
            }
        oid, size = self.identity()
        return {
            "path": self.path,
            "oid": oid,
            "size": size,
            "inline": not self.is_pointer,
        }


def _directory_matches(reference: DirectoryRef, directory: Path) -> bool:
    if not directory.is_dir():
        return False
    try:
        files(directory)  # Reject links before inspecting a mutable cache tree.
        members, empty = _directory_entries(directory)
        actual = {path: hash_file(physical) for path, physical in members}
    except (OSError, StoreError):
        return False
    expected = {
        Path(item.path).relative_to(reference.path).as_posix(): (item.oid, item.size)
        for item in reference.members
    }
    expected_empty = {
        Path(path).relative_to(reference.path).as_posix()
        for path in reference.empty_directories
    }
    return actual == expected and set(empty) == expected_empty


def _write_directory_reference(
    store: Store, reference: DirectoryRef, destination: Path
) -> None:
    parent = store.projects.get(reference.project).runs.get(reference.run)
    if (
        isinstance(parent, DraftRun)
        or parent.metadata.get("git", {}).get("commit") != reference.code_commit
    ):
        raise IntegrityError(
            "directory reference does not match a published source identity"
        )
    destination.mkdir(parents=True, exist_ok=True)
    for member in reference.members:
        payload = store.object_path(member.oid, size=member.size)
        _copy(
            payload,
            contained(destination, Path(member.path).relative_to(reference.path)),
        )
    for path in reference.empty_directories:
        relative = Path(path).relative_to(reference.path)
        target = destination if relative == Path() else contained(destination, relative)
        target.mkdir(parents=True, exist_ok=True)


class RunMetrics:
    def __init__(self, run: Run) -> None:
        self.run = run

    def scan(self) -> Any:
        import polars as pl

        path = self.run.directory / "metrics.parquet"
        if path.exists():
            return pl.scan_parquet(path)
        return pl.DataFrame(
            schema={
                "name": pl.String,
                "step": pl.Int64,
                "timestamp_ms": pl.Int64,
                "value": pl.Float64,
            }
        ).lazy()


def _delete_ref(project: Project, run_id: str) -> None:
    subprocess.run(
        [
            "git",
            "--git-dir",
            str(project.archive),
            "update-ref",
            "-d",
            f"refs/runs/{run_id}",
        ],
        check=True,
        capture_output=True,
    )


class RunEditor:
    """Stage changed files and metadata, then install them from a durable journal."""

    def __init__(self, run: Run) -> None:
        self.run = run
        self.metadata = copy.deepcopy(run.metadata)
        self._original = copy.deepcopy(self.metadata)
        self.tags = set(self.metadata.get("tags", []))
        self.transaction: Path | None = None
        self.removed: set[str] = set()

    @property
    def name(self) -> str:
        return self.metadata["name"]

    @name.setter
    def name(self, value: str) -> None:
        self.metadata["name"] = value

    def __enter__(self) -> Self:
        self.run.validate(objects=False)
        self.transaction = self.run.store._transaction(
            "edit", project=self.run.project.id, run=self.run.id
        )
        (self.transaction / "after").mkdir()
        return self

    def _stage(self, path: str, *, copy_existing: bool = False) -> Path:
        if self.transaction is None:
            raise ConflictError("run editor must be entered as a context")
        path = relative_path(path)
        self._mutable_file(path.removesuffix(".lfs"))
        target = contained(self.transaction / "after", path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if copy_existing and not target.exists():
            original = contained(self.run.directory, path)
            if original.is_file():
                _copy(original, target)
        self.removed.discard(path)
        return target

    def _mutable_file(self, path: str) -> None:
        if path in {"run.yaml", "run.log", "metrics.parquet", "metrics.jsonl"}:
            raise ConflictError(f"execution evidence cannot be edited: {path}")
        if path.startswith("scratch/"):
            raise ConflictError("scratch is not part of a published run")
        for binding in _directory_bindings(self._original):
            root = binding["input"]
            if binding.get("consumed", True) and (
                Path(path).is_relative_to(root) or Path(root).is_relative_to(path)
            ):
                raise ConflictError(
                    f"consumed directory input cannot be edited: {root}"
                )
        for binding in _input_bindings(self._original):
            if binding.get("consumed", True) and binding["input"] == path:
                raise ConflictError(f"consumed input cannot be edited: {path}")

    def report(self, name: str) -> Path:
        return self._stage(_report_name(name), copy_existing=True)

    def asset(self, name: str, *, source: str | Path) -> Path:
        return self.add_file(source, path="assets/" + relative_path(name), inline=True)

    def inline_file(self, source: str | Path, *, path: str) -> Path:
        return self.add_file(source, path=path, inline=True)

    def add_file(  # noqa: C901, PLR0912 - stage files, local directories and pinned directory attachments
        self,
        source: str | Path | FileRef | DirectoryRef,
        *,
        path: str,
        inline: bool = False,
    ) -> Path:
        path = relative_path(path)
        self._mutable_file(path)
        attachment: dict = {"path": path, "attached_at": now()}
        if isinstance(source, DirectoryRef):
            parent = self.run.store.projects.get(source.project).runs.get(source.run)
            if (
                isinstance(parent, DraftRun)
                or parent.metadata.get("git", {}).get("commit") != source.code_commit
            ):
                raise IntegrityError(
                    "directory reference does not match a published source identity"
                )
            members: list[str] = []
            for member in source.members:
                logical = (
                    Path(path) / Path(member.path).relative_to(source.path)
                ).as_posix()
                self.add_file(member, path=logical, inline=inline)
                members.append(logical)
            empty = [
                (Path(path) / Path(item).relative_to(source.path)).as_posix()
                for item in source.empty_directories
            ]
            self.metadata.setdefault("file_groups", []).append(
                {"path": path, "files": members, "empty_directories": empty}
            )
            self.metadata.setdefault("attachments", []).append(
                {
                    **attachment,
                    "source": {
                        key: getattr(source, key)
                        for key in ("project", "run", "path", "code_commit", "bound_at")
                    },
                }
            )
            return self._stage(path)
        if isinstance(source, FileRef):
            parent = self.run.store.projects.get(source.project).runs.get(source.run)
            if (
                isinstance(parent, DraftRun)
                or parent.metadata.get("git", {}).get("commit") != source.code_commit
            ):
                raise IntegrityError(
                    "attachment reference does not match a published source identity"
                )
            payload = self.run.store.object_path(source.oid, size=source.size)
            attachment["source"] = source.to_dict()
        else:
            payload = Path(source).expanduser().resolve(strict=True)
        if payload.is_dir():
            entries, directories = _directory_entries(
                payload, target=contained(self.run.directory, path)
            )
            empty = [(Path(path) / relative).as_posix() for relative in directories]
            members = [(Path(path) / relative).as_posix() for relative, _ in entries]
            for (_relative, physical), member in zip(entries, members, strict=True):
                self.add_file(physical, path=member, inline=inline)
            self.metadata.setdefault("file_groups", []).append(
                {"path": path, "files": members, "empty_directories": empty}
            )
            return self._stage(path)
        if not payload.is_file():
            raise IntegrityError(f"attachment is not a regular file: {payload}")
        if inline or _inline(path) or isinstance(self.run, DraftRun):
            target = self._stage(path)
            _copy(payload, target)
            pointer = path + ".lfs"
            if contained(self.run.directory, pointer).exists():
                self.removed.add(pointer)
        else:
            stored = (
                Result(oid=source.oid, size=source.size, path=payload)
                if isinstance(source, FileRef)
                else self.run.store._put(payload, logical_path=path)
            )
            target = self._stage(path + ".lfs")
            atomic_bytes(target, pointer_bytes(stored["oid"], stored["size"]))
            if contained(self.run.directory, path).exists():
                self.removed.add(path)
        self.metadata.setdefault("attachments", []).append(attachment)
        return target

    def remove_file(self, path: str) -> None:
        path = relative_path(path)
        self._mutable_file(path)
        item = self.run.file(path)
        physical = item.physical_path.relative_to(self.run.directory).as_posix()
        self.removed.add(physical)
        if self.transaction is not None:
            staged = contained(self.transaction / "after", physical)
            staged.unlink(missing_ok=True)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:  # noqa: C901 - journal assembly precedes every live change
        if self.transaction is None:
            return False
        if exc_type is not None:
            shutil.rmtree(self.transaction)
            return False
        # Direct metadata editing and the tags convenience set are both supported.
        if self.metadata.get("tags", []) == self._original.get("tags", []):
            self.metadata["tags"] = sorted(self.tags)
        if _immutable(self.metadata) != _immutable(self._original):
            shutil.rmtree(self.transaction)
            raise ConflictError("execution evidence cannot be changed by an edit")
        if self.run.metadata != self._original:
            shutil.rmtree(self.transaction)
            raise ConflictError("run metadata changed while an edit was staged")
        self.metadata["updated_at"] = now()
        after = self.transaction / "after"
        write_yaml(after / "run.yaml", self.metadata)
        try:
            _validate_overlay(self.run, after, self.removed)
            changes = []
            paths = self.removed | {
                path.relative_to(after).as_posix() for path in files(after)
            }
            for name in sorted(paths, key=lambda value: (value == "run.yaml", value)):
                current = contained(self.run.directory, name)
                staged = contained(after, name)
                old_identity = hash_file(current) if current.exists() else None
                new_identity = hash_file(staged) if staged.exists() else None
                if old_identity == new_identity:
                    continue
                if current.exists():
                    _copy(current, contained(self.transaction / "before", name))
                changes.append(
                    {
                        "path": name,
                        "old": list(old_identity) if old_identity else None,
                        "new": list(new_identity) if new_identity else None,
                    }
                )
            journal = {
                "kind": "edit",
                "phase": "applying",
                "project": self.run.project.id,
                "run": self.run.id,
                "changes": changes,
            }
            _sync_tree(self.transaction)
            write_yaml(self.transaction / "journal.yaml", journal)
        except (StoreError, OSError, ValueError):
            shutil.rmtree(self.transaction)
            raise
        _recover_edit(self.run.store, self.transaction, journal)
        if isinstance(self.run, DraftRun):
            self.run.metadata.clear()
            self.run.metadata.update(read_yaml(self.run.directory / "run.yaml"))
        # The journal has already confirmed the authoritative edit.
        with contextlib.suppress(OSError, sqlite3.Error, StoreError):
            self.run.store.index.update(self.run)
        return False


def _validate_overlay(run: Run, after: Path, removed: set[str]) -> None:
    mapping = {
        path.relative_to(run.directory).as_posix(): path
        for path in files(run.directory)
    }
    mapping.update({path.relative_to(after).as_posix(): path for path in files(after)})
    for name in removed:
        mapping.pop(name, None)
    _validate_planned_references(run, mapping)
    for name, physical in mapping.items():
        if Path(name).suffix.lower() not in {".html", ".htm", ".css"}:
            continue
        content = physical.read_text(errors="replace")
        links = re.findall(r"(?:src|href)\s*=\s*[\"']([^\"']+)", content, re.IGNORECASE)
        links += re.findall(r"url\(\s*[\"']?([^\"')\s]+)", content, re.IGNORECASE)
        for link in links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            base = run.directory / Path(name).parent
            path = (base / unquote(parsed.path)).resolve()
            if parsed.path.startswith("/") or not path.is_relative_to(
                run.directory.resolve()
            ):
                raise IntegrityError(f"report resource escapes run: {name}: {link}")
            logical = path.relative_to(run.directory).as_posix()
            if logical not in mapping and not any(
                key.startswith(logical + "/") for key in mapping
            ):
                raise IntegrityError(f"report resource is missing: {name}: {link}")


def _validate_planned_references(run: Run, mapping: dict[str, Path]) -> None:
    """Reject an invalid complete edit before replacing any live file."""
    metadata = read_yaml(mapping["run.yaml"])
    logical_files = {
        name.removesuffix(".lfs")
        if name.endswith(".lfs") and not _inline(name)
        else name
        for name in mapping
    }
    _validate_planned_groups(metadata, logical_files)
    _validate_planned_inputs(metadata, mapping)
    for binding in _directory_bindings(metadata):
        if binding.get("consumed", True):
            _validate_planned_directory(run, metadata, binding, logical_files)
    for project, run_id in _source_edges(run, metadata=metadata):
        if isinstance(run.store.projects.get(project).runs.get(run_id), DraftRun):
            raise IntegrityError(f"planned source is unpublished: {project}/{run_id}")


def _validate_planned_groups(metadata: dict, logical_files: set[str]) -> None:
    for group in metadata.get("file_groups", []):
        members = [
            *group.get("files", []),
            *([group["main"]] if "main" in group else []),
        ]
        for member in members:
            if relative_path(member) not in logical_files:
                raise IntegrityError(
                    f"required companion is missing from planned edit: {member}"
                )
        for empty in group.get("empty_directories", []):
            relative_path(empty)


def _validate_planned_inputs(metadata: dict, mapping: dict[str, Path]) -> None:
    for binding in _input_bindings(metadata):
        if not binding.get("consumed", True):
            continue
        logical = relative_path(binding["input"])
        physical = mapping.get(logical + ".lfs", mapping.get(logical))
        if physical is None:
            raise IntegrityError(
                f"consumed input is missing from planned edit: {logical}"
            )
        identity = _is_data_pointer(logical, physical) or hash_file(physical)
        if identity != (binding["oid"], binding["size"]):
            raise IntegrityError(f"consumed input changed in planned edit: {logical}")


def _validate_planned_directory(
    run: Run, metadata: dict, binding: dict, logical_files: set[str]
) -> None:
    root = relative_path(binding["input"])
    prefix = root + "/"
    members = {name for name in logical_files if name.startswith(prefix)}
    empty = set()
    physical = contained(run.directory, root)
    if physical.is_dir():
        empty.update(
            (Path(root) / path).as_posix() for path in _empty_directories(physical)
        )
    for group in metadata.get("file_groups", []):
        empty.update(
            path
            for path in group.get("empty_directories", [])
            if path == root or path.startswith(prefix)
        )
    empty = {
        path
        for path in empty
        if not any(name.startswith(path + "/") for name in members)
    }
    empty = {
        path
        for path in empty
        if not any(other != path and other.startswith(path + "/") for other in empty)
    }
    if not members and not empty:
        empty.add(root)
    if members != set(binding["members"]) or empty != set(binding["empty_directories"]):
        raise IntegrityError(
            f"consumed directory topology changed in planned edit: {root}"
        )


def _recover_edit(store: Store, transaction: Path, journal: dict) -> None:
    if journal["phase"] == "prepared":
        shutil.rmtree(transaction)
        return
    run = store.projects.get(journal["project"]).runs.get(journal["run"])
    for change in journal["changes"]:
        target = contained(run.directory, change["path"])
        identity = list(hash_file(target)) if target.exists() else None
        if identity == change["new"]:
            continue
        if identity != change["old"]:
            raise ConflictError(f"file changed outside the interrupted edit: {target}")
        if change["new"] is None:
            target.unlink(missing_ok=True)
            fsync_dir(target.parent)
        else:
            staged = contained(transaction / "after", change["path"])
            if list(hash_file(staged)) != change["new"]:
                raise IntegrityError(f"edit staging bytes changed: {staged}")
            _copy(staged, target)
    run.validate(objects=True)
    journal["phase"] = "committed"
    write_yaml(transaction / "journal.yaml", journal)
    shutil.rmtree(transaction)


def _recover_save(store: Store, transaction: Path, journal: dict) -> Path | None:
    project = store.projects.get(journal["project"])
    final = contained(project.directory / "runs", journal["run"])
    draft = contained(project.directory / "runs", journal["run"] + ".tmp")
    if final.is_dir():
        if draft.exists():
            raise ConflictError(f"publication has conflicting directories: {final}")
        Run(project, journal["run"], final).validate(objects=True)
        fsync_dir(final.parent)
        shutil.rmtree(transaction)
        return None
    cleanup = transaction / "cleanup"
    if cleanup.exists():
        if not draft.exists():
            raise IntegrityError(f"save workspace is missing: {draft}")
        for child in cleanup.iterdir():
            if (draft / child.name).exists():
                raise ConflictError(
                    f"save cleanup conflicts with preserved work: {child.name}"
                )
            child.replace(draft / child.name)
            fsync_dir(draft)
    shutil.rmtree(transaction)
    return draft


def _recover_copy(store: Store, transaction: Path, journal: dict) -> None:
    project = store.projects.get(journal["project"])
    final = contained(project.directory / "runs", journal["run"])
    temporary = contained(project.directory / "runs", journal["run"] + ".tmp")
    if (
        final.exists()
        and Run(project, journal["run"], final).fingerprint == journal["fingerprint"]
    ):
        Run(project, journal["run"], final).validate(objects=True)
        fsync_dir(final.parent)
        shutil.rmtree(transaction)
        return
    if journal["phase"] == "prepared":
        # The source remains intact; only discard the explicitly owned incomplete copy.
        if journal.get("temporary_created") and temporary.exists():
            shutil.rmtree(temporary)
            fsync_dir(temporary.parent)
        shutil.rmtree(transaction)
        return
    staged = Run(project, journal["run"], temporary)
    staged.validate(objects=True)
    if staged.fingerprint != journal["fingerprint"]:
        raise IntegrityError("copy staging does not match its publication intent")
    for parent_project, parent_id in journal.get("parents", []):
        parent = store.projects.get(parent_project).runs.get(parent_id)
        if isinstance(parent, DraftRun):
            raise IntegrityError(f"copy source closure is incomplete: {parent_id}")
        parent.validate(objects=False)
    if final.exists():
        old = Run(project, journal["run"], final)
        if old.fingerprint != journal.get("old_fingerprint"):
            raise ConflictError("copy target changed after its publication intent")
        final.replace(transaction / "previous")
    temporary.replace(final)
    fsync_dir(final.parent)
    Run(project, journal["run"], final).validate(objects=True)
    shutil.rmtree(transaction)


def _source_edges(run: Run, *, metadata: dict | None = None) -> set[tuple[str, str]]:
    metadata = run.metadata if metadata is None else metadata
    edges = {(item["project"], item["run"]) for item in metadata.get("sources", [])}
    edges.update(
        (item["project"], item["run"])
        for item in metadata.get("input_bindings", [])
        if "project" in item and "run" in item
    )
    for binding in _directory_bindings(metadata):
        if "source" in binding:
            edges.add((binding["source"]["project"], binding["source"]["run"]))
    edges.update((item["project"], item["run"]) for item in metadata.get("parents", []))
    for attachment in metadata.get("attachments", []):
        if isinstance(attachment.get("source"), dict):
            item = attachment["source"]
            edges.add((item["project"], item["run"]))
    source_run = metadata.get("source_run")
    if isinstance(source_run, dict):
        edges.add((source_run["project"], source_run["run"]))
    elif isinstance(source_run, str):
        edges.add((run.project.id, source_run))
    return edges


def _delete_runs(
    store: Store, selected: set[tuple[str, str]], *, dry_run: bool
) -> Result:
    store._writable()
    runs = [
        store.projects.get(project).runs.get(id) for project, id in sorted(selected)
    ]
    for run in runs:
        if isinstance(run, DraftRun):
            raise ConflictError(f"unpublished run cannot be deleted: {run.id}")
        run.validate(objects=False)
    retained_oids: set[str] = set()
    for project in store.projects:
        for retained in project.runs:
            if (project.id, retained.id) in selected:
                continue
            if _source_edges(retained) & selected:
                raise ConflictError(
                    f"retained run {project.id}/{retained.id} depends on selection"
                )
            retained.validate(objects=False)
            retained_oids.update(
                item.identity()[0] for item in retained.files() if item.is_pointer
            )
    selected_oids = {
        item.identity()[0] for run in runs for item in run.files() if item.is_pointer
    }
    directory_bytes = sum(_bytes_in(run.directory) for run in runs)
    asset_bytes = sum(
        _bytes_in(run.directory / "assets")
        for run in runs
        if (run.directory / "assets").exists()
    )
    exclusive = sum(
        store.object_path(oid, verify=False).stat().st_size
        for oid in selected_oids - retained_oids
    )
    shared = sum(
        store.object_path(oid, verify=False).stat().st_size
        for oid in selected_oids & retained_oids
    )
    result = Result(
        dry_run=dry_run,
        runs=[{"project": run.project.id, "run": run.id} for run in runs],
        directory_bytes=directory_bytes,
        asset_bytes=asset_bytes,
        exclusive_cas_bytes=exclusive,
        shared_cas_bytes=shared,
        released_bytes=0,
        warnings=[],
    )
    if dry_run or not runs:
        return result
    transaction = store._transaction(
        "delete",
        runs=[
            {
                "project": run.project.id,
                "run": run.id,
                "fingerprint": run.fingerprint,
            }
            for run in runs
        ],
    )
    journal = read_yaml(transaction / "journal.yaml")
    journal["phase"] = "deleting"
    write_yaml(transaction / "journal.yaml", journal)
    try:
        store._finish_delete(transaction, journal)
        result["released_bytes"] = directory_bytes
    except OSError as error:
        remaining = (
            _bytes_in(transaction / "trash") if (transaction / "trash").exists() else 0
        )
        remaining += sum(
            _bytes_in(run.directory) for run in runs if run.directory.exists()
        )
        result["released_bytes"] = directory_bytes - remaining
        result["warnings"].append(f"deletion cleanup pending: {error}")
    try:
        store.index.refresh()
    except (OSError, sqlite3.Error, StoreError) as error:
        result["warnings"].append(f"index refresh failed: {error}")
    return result


_QUERY_FIELDS = {
    "id",
    "project",
    "name",
    "kind",
    "status",
    "created_at",
    "started_at",
    "ended_at",
    "updated_at",
    "tags",
    "parameters",
    "metrics",
    "execution",
    "git",
}
_QUERY_NODES = (
    ast.Expression,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Subscript,
    ast.Attribute,
    ast.Compare,
    ast.BoolOp,
    ast.UnaryOp,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.List,
    ast.Tuple,
    ast.Is,
    ast.IsNot,
)


def _query_expression(expression: str) -> ast.AST:
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise IntegrityError(f"invalid query expression: {expression}") from error
    for node in ast.walk(parsed):
        if not isinstance(node, _QUERY_NODES):
            raise IntegrityError(
                f"query operation is not allowed: {type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id not in _QUERY_FIELDS:
            raise IntegrityError(f"unknown query field: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise IntegrityError(f"invalid query attribute: {node.attr}")
        if isinstance(node, ast.Subscript) and not (
            isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, (str, int))
        ):
            raise IntegrityError("query subscript must be a literal field name")
    return parsed.body


def _query_value(node: ast.AST, metadata: Mapping[str, Any]) -> Any:  # noqa: C901, PLR0911, PLR0912 - explicit dispatch over the allowed AST nodes
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return metadata.get(node.id)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_query_value(item, metadata) for item in node.elts]
    if isinstance(node, (ast.Subscript, ast.Attribute)):
        base = _query_value(node.value, metadata)
        key = node.attr if isinstance(node, ast.Attribute) else node.slice.value
        value = base.get(key) if isinstance(base, Mapping) else None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if key == "last" and value in ("NaN", "Infinity", "-Infinity"):
            return None
        return value
    if isinstance(node, ast.BoolOp):
        values = (_query_value(item, metadata) for item in node.values)
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp):
        operand = _query_value(node.operand, metadata)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(operand, (int, float)) and not isinstance(operand, bool):
            return -operand if isinstance(node.op, ast.USub) else operand
        raise IntegrityError("query sign operators require a number")
    if isinstance(node, ast.Compare):
        left = _query_value(node.left, metadata)
        for operation, comparator in zip(node.ops, node.comparators, strict=True):
            right = _query_value(comparator, metadata)
            try:
                if isinstance(operation, (ast.Eq, ast.Is)):
                    passed = left == right
                elif isinstance(operation, (ast.NotEq, ast.IsNot)):
                    passed = left != right
                elif isinstance(operation, ast.Lt):
                    passed = left < right
                elif isinstance(operation, ast.LtE):
                    passed = left <= right
                elif isinstance(operation, ast.Gt):
                    passed = left > right
                elif isinstance(operation, ast.GtE):
                    passed = left >= right
                elif isinstance(operation, ast.In):
                    passed = left in right
                else:
                    passed = left not in right
            except TypeError:
                passed = False
            if not passed:
                return False
            left = right
        return True
    raise IntegrityError(f"unsupported query expression: {type(node).__name__}")


class Index:
    """A replaceable, machine-local SQLite cache; never a GC authority."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.path = store.cache_root / "index.sqlite"
        self.last_refreshed_at: str | None = None

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path)
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("SQLite integrity check failed")  # noqa: TRY301 - one cache recreation path
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                connection.close()
                raise sqlite3.DatabaseError("unknown index schema")  # noqa: TRY301 - one cache recreation path
        except sqlite3.DatabaseError:
            with contextlib.suppress(UnboundLocalError, sqlite3.Error):
                connection.close()
            if self.path.exists():
                self.path.rename(self.path.with_name(f"index.{uuid7()}.corrupt"))
            connection = sqlite3.connect(self.path)
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                project TEXT NOT NULL, id TEXT NOT NULL, metadata TEXT NOT NULL,
                fingerprint TEXT NOT NULL, PRIMARY KEY(project,id));
            CREATE TABLE IF NOT EXISTS tags (project TEXT, run TEXT, tag TEXT);
            CREATE TABLE IF NOT EXISTS parameters (project TEXT, run TEXT, name TEXT, type TEXT, value TEXT);
            CREATE TABLE IF NOT EXISTS metrics (project TEXT, run TEXT, name TEXT, summary TEXT);
            CREATE TABLE IF NOT EXISTS files (project TEXT, run TEXT, path TEXT, oid TEXT, size INTEGER, inline INTEGER);
            CREATE TABLE IF NOT EXISTS sources (project TEXT, run TEXT, source_project TEXT, source_run TEXT);
            PRAGMA user_version=1;
        """)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _row(self, run: Run) -> tuple[dict, str, list[dict]]:
        metadata = run.metadata
        if (
            metadata.get("schema_version") != 1
            or metadata.get("id") != run.id
            or metadata.get("project") != run.project.id
        ):
            raise IntegrityError(
                f"invalid run identity during indexing: {run.directory}"
            )
        entries = []
        for item in run.files():
            pointer = item.is_pointer
            oid, size = (
                item.identity()
                if pointer
                else (None, item.physical_path.stat().st_size)
            )
            entries.append(
                {"path": item.path, "oid": oid, "size": size, "inline": not pointer}
            )
        return metadata, fingerprint({"metadata": metadata, "files": entries}), entries

    def _write(
        self,
        connection: sqlite3.Connection,
        run: Run,
        metadata: dict,
        control: str,
        entries: list[dict],
    ) -> None:
        key = (run.project.id, run.id)
        connection.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?)",
            (*key, json.dumps(metadata), control),
        )
        for table in ("tags", "parameters", "metrics", "files", "sources"):
            connection.execute(f"DELETE FROM {table} WHERE project=? AND run=?", key)  # noqa: S608 - fixed internal schema names
        connection.executemany(
            "INSERT INTO tags VALUES (?,?,?)",
            [(*key, tag) for tag in metadata.get("tags", [])],
        )
        connection.executemany(
            "INSERT INTO parameters VALUES (?,?,?,?,?)",
            [
                (*key, name, type(value).__name__, json.dumps(value))
                for name, value in metadata.get("parameters", {}).items()
            ],
        )
        connection.executemany(
            "INSERT INTO metrics VALUES (?,?,?,?)",
            [
                (*key, name, json.dumps(summary))
                for name, summary in metadata.get("metrics", {}).items()
            ],
        )
        connection.executemany(
            "INSERT INTO files VALUES (?,?,?,?,?,?)",
            [
                (*key, item["path"], item["oid"], item["size"], item["inline"])
                for item in entries
            ],
        )
        connection.executemany(
            "INSERT INTO sources VALUES (?,?,?,?)",
            [(*key, *edge) for edge in _source_edges(run)],
        )

    def rebuild(self) -> Result:
        return self.refresh(rebuild=True)

    def refresh(self, *, rebuild: bool = False) -> Result:
        changed = 0
        seen: set[tuple[str, str]] = set()
        with self._connect() as connection:
            if rebuild:
                for table in (
                    "runs",
                    "tags",
                    "parameters",
                    "metrics",
                    "files",
                    "sources",
                ):
                    connection.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed internal schema names
            for project in self.store.projects:
                for run in project.runs:
                    metadata, control, entries = self._row(run)
                    key = (project.id, run.id)
                    seen.add(key)
                    old = connection.execute(
                        "SELECT fingerprint FROM runs WHERE project=? AND id=?", key
                    ).fetchone()
                    if old is None or old[0] != control:
                        self._write(connection, run, metadata, control, entries)
                        changed += 1
            for key in connection.execute("SELECT project,id FROM runs").fetchall():
                if tuple(key) not in seen:
                    connection.execute("DELETE FROM runs WHERE project=? AND id=?", key)
                    for table in ("tags", "parameters", "metrics", "files", "sources"):
                        connection.execute(
                            f"DELETE FROM {table} WHERE project=? AND run=?",  # noqa: S608 - fixed internal schema names
                            key,
                        )
            self.last_refreshed_at = now()
            connection.execute(
                "INSERT OR REPLACE INTO cache_meta VALUES ('refreshed_at',?)",
                (self.last_refreshed_at,),
            )
        return Result(
            runs=len(seen),
            updated=changed,
            refreshed_at=self.last_refreshed_at,
            rebuilt=rebuild,
        )

    def update(self, run: Run) -> None:
        with self._connect() as connection:
            initialized = connection.execute(
                "SELECT value FROM cache_meta WHERE key='refreshed_at'"
            ).fetchone()
        if initialized is None:
            self.rebuild()
            return
        metadata, control, entries = self._row(run)
        with self._connect() as connection:
            self._write(connection, run, metadata, control, entries)
            self.last_refreshed_at = now()
            connection.execute(
                "INSERT OR REPLACE INTO cache_meta VALUES ('refreshed_at',?)",
                (self.last_refreshed_at,),
            )

    def query(  # noqa: C901 - combines declared filters and stable sorting
        self,
        *,
        project: str | None = None,
        tags: Iterable[str] = (),
        status: str | Iterable[str] | None = None,
        kind: str | Iterable[str] | None = None,
        where: str | None = None,
        sort: str | Iterable[str] = "-created_at",
        limit: int | None = None,
        refresh: bool = False,
        **_: Any,
    ) -> list[Result]:
        expression = _query_expression(where) if where else None
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise IntegrityError("query limit must be a nonnegative integer")
        if refresh:
            self.refresh()
        with self._connect() as connection:
            stamp = connection.execute(
                "SELECT value FROM cache_meta WHERE key='refreshed_at'"
            ).fetchone()
        if stamp is None:
            self.rebuild()
        with self._connect() as connection:
            self.last_refreshed_at = connection.execute(
                "SELECT value FROM cache_meta WHERE key='refreshed_at'"
            ).fetchone()[0]
            if project is None:
                records = connection.execute("SELECT metadata FROM runs").fetchall()
            else:
                records = connection.execute(
                    "SELECT metadata FROM runs WHERE project=?", (project,)
                ).fetchall()
        required_tags = set(tags)
        statuses = {status} if isinstance(status, str) else set(status or [])
        kinds = {kind} if isinstance(kind, str) else set(kind or [])
        rows = []
        for (encoded,) in records:
            metadata = json.loads(encoded)
            if required_tags - set(metadata.get("tags", [])):
                continue
            if statuses and metadata.get("status") not in statuses:
                continue
            if kinds and metadata.get("kind") not in kinds:
                continue
            if expression is not None and not _query_value(expression, metadata):
                continue
            rows.append(Result(metadata))
        fields = [sort] if isinstance(sort, str) else list(sort)
        for field in reversed(fields):
            reverse = field.startswith("-")
            node = _query_expression(field.lstrip("-+"))

            def sort_key(row: dict, node: ast.AST = node) -> tuple:
                value = _query_value(node, row)
                return (
                    value is None,
                    type(value).__name__,
                    value if isinstance(value, (str, int, float)) else str(value),
                )

            rows.sort(key=sort_key, reverse=reverse)
        return rows[:limit] if limit is not None else rows


def _run_closure(selected: list[Run]) -> list[Run]:
    ordered: list[Run] = []
    visited: set[tuple[str, str]] = set()
    active: set[tuple[str, str]] = set()

    def visit(run: Run) -> None:
        key = (run.project.id, run.id)
        if key in active:
            raise IntegrityError(f"source dependency cycle: {key}")
        if key in visited:
            return
        if isinstance(run, DraftRun):
            raise ConflictError(f"cannot archive unpublished source: {key}")
        run.validate(objects=True)
        active.add(key)
        for project, id in sorted(_source_edges(run)):
            visit(run.store.projects.get(project).runs.get(id))
        active.remove(key)
        visited.add(key)
        ordered.append(run)

    for run in selected:
        visit(run)
    return ordered


def _ref_commit(project: Project, run: str) -> str | None:
    process = subprocess.run(
        [
            "git",
            "--git-dir",
            str(project.archive),
            "rev-parse",
            "--verify",
            f"refs/runs/{run}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip() if process.returncode == 0 else None


def _copy_runs(  # noqa: C901, PLR0912, PLR0915 - preflight, transfer and publication remain ordered
    selected: list[Run],
    target_store: Store | str | Path,
    *,
    replace: bool,
    expected_target: str | dict | None,
) -> Result:
    target = (
        target_store if isinstance(target_store, Store) else Store.open(target_store)
    )
    target._writable()
    if not selected:
        return Result(ok=True, runs=[], warnings=[])
    closure = _run_closure(selected)
    if target.root == selected[0].store.root:
        return Result(
            ok=True,
            runs=[
                {
                    "project": run.project.id,
                    "run": run.id,
                    "status": "identical",
                    "fingerprint": run.fingerprint,
                }
                for run in closure
            ],
            warnings=[],
        )
    existing: dict[tuple[str, str], Run] = {}
    target_fingerprints: dict[tuple[str, str], str] = {}
    fingerprints: dict[tuple[str, str], str] = {}
    # Preflight the whole selection before transferring or replacing any payload.
    for run in closure:
        key = (run.project.id, run.id)
        fingerprints[key] = run.fingerprint
        try:
            destination_project = target.projects.get(run.project.id)
            destination = destination_project.runs.get(run.id)
        except NotFoundError:
            continue
        if isinstance(destination, DraftRun):
            raise ConflictError(f"target has an unpublished run: {key}")
        destination.validate(objects=True)
        existing[key] = destination
        target_fingerprints[key] = destination.fingerprint
        if _immutable(destination.metadata) != _immutable(run.metadata):
            raise ConflictError(f"same run ID has different execution evidence: {key}")
        source_commit = run.metadata.get("git", {}).get("commit")
        target_commit = _ref_commit(destination_project, run.id)
        if (
            source_commit
            and target_commit is not None
            and target_commit != source_commit
        ):
            raise ConflictError(f"target code ref differs: {key}")
        if destination.fingerprint == fingerprints[key]:
            continue
        expected = (
            expected_target.get("/".join(key))
            if isinstance(expected_target, dict)
            else expected_target
        )
        if not replace or expected is None or expected != destination.fingerprint:
            raise ConflictError(
                f"target mutable content differs; explicit matching replacement fingerprint required: {key}"
            )
    copied_projects: set[str] = set()
    receipts: list[dict] = []
    warnings: list[str] = []
    for run in closure:
        key = (run.project.id, run.id)
        if run.fingerprint != fingerprints[key]:
            raise ConflictError(f"source run changed during copy: {key}")
        if run.project.id not in copied_projects:
            destination_project = target.projects.add(run.project.id)
            from ._source import copy_archive

            copy_archive(run.project, destination_project)
            copied_projects.add(run.project.id)
        destination_project = target.projects.get(run.project.id)
        old = existing.get(key)
        if old is not None and old.fingerprint == fingerprints[key]:
            receipts.append(
                {
                    "project": key[0],
                    "run": key[1],
                    "status": "identical",
                    "fingerprint": fingerprints[key],
                    "verified": True,
                }
            )
            continue
        # Every pointer and consumed historical identity is copied by digest.
        identities = {item.identity() for item in run.files() if item.is_pointer}
        for field in ("input_bindings", "sources"):
            identities.update(
                (item["oid"], item["size"])
                for item in run.metadata.get(field, [])
                if "oid" in item
            )
        for oid, size in identities:
            payload = run.store.object_path(oid, size=size)
            target._put(
                payload, suffix=payload.name.split(".", 1)[1], interpret_pointer=False
            )
        transaction = target._transaction(
            "copy",
            project=run.project.id,
            run=run.id,
            fingerprint=fingerprints[key],
            old_fingerprint=target_fingerprints.get(key),
            parents=[list(edge) for edge in _source_edges(run)],
        )
        temporary = destination_project.directory / "runs" / (run.id + ".tmp")
        if temporary.exists():
            raise ConflictError(f"target temporary run exists: {key}")
        temporary.mkdir()
        journal = read_yaml(transaction / "journal.yaml")
        journal["temporary_created"] = True
        write_yaml(transaction / "journal.yaml", journal)
        try:
            for physical in files(run.directory):
                _copy(
                    physical, contained(temporary, physical.relative_to(run.directory))
                )
            _copy_empty_directories(run.directory, temporary)
            staged = Run(destination_project, run.id, temporary)
            staged.validate(objects=True)
            if (
                staged.fingerprint != fingerprints[key]
                or run.fingerprint != fingerprints[key]
            ):
                raise IntegrityError(f"source/control bytes changed during copy: {key}")
            for parent_project, parent_run in _source_edges(run):
                parent = target.projects.get(parent_project).runs.get(parent_run)
                if isinstance(parent, DraftRun):
                    raise IntegrityError(
                        f"source closure has not been published: {parent_run}"
                    )
                parent.validate(objects=False)
            journal["phase"] = "staged"
            _sync_tree(temporary)
            write_yaml(transaction / "journal.yaml", journal)
            destination = temporary.with_name(run.id)
            if destination.exists():
                if old is None or old.fingerprint != target_fingerprints[key]:
                    raise ConflictError(f"target changed during copy: {key}")
                destination.replace(transaction / "previous")
                fsync_dir(destination.parent)
            temporary.replace(destination)
            fsync_dir(destination.parent)
            published = Run(destination_project, run.id, destination)
            published.validate(objects=True)
            receipts.append(
                {
                    "project": key[0],
                    "run": key[1],
                    "status": "replaced" if old else "copied",
                    "fingerprint": published.fingerprint,
                    "verified": True,
                }
            )
            shutil.rmtree(transaction)
            try:
                target.index.update(published)
            except (OSError, StoreError, sqlite3.Error) as error:
                warnings.append(f"index update failed for {key}: {error}")
        except (OSError, StoreError, ValueError) as error:
            error.copy_result = Result(ok=False, runs=receipts, warnings=[str(error)])
            raise
    return Result(ok=True, runs=receipts, warnings=warnings, store=target.id)

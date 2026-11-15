# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003, SLF001
"""Manifest-backed local files and remote content-addressed run records."""

from __future__ import annotations

import contextlib
import copy as copying
import errno
import fcntl
import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from . import _git
from ._io import (
    DATA_DIRS,
    FIELDS,
    artifact_entries,
    collect_artifacts,
    copy,
    identity,
    mutable,
    read_yaml,
    run_relative_path,
    write_yaml,
)
from ._runtime import METRIC_SCHEMA

_EDITABLE = {"run-name", "description", "tags", "metadata"}
_DATE_PATTERN = "????/??/??"
_RUN_PATTERN = _DATE_PATTERN + "/*/run.yaml"


@contextlib.contextmanager
def _write_lock(store: LocalStore | RemoteStore) -> Generator[None, None, None]:
    """Serialize remote mutations and GC on this client without remote sidecars."""
    if not isinstance(store, RemoteStore):
        yield
        return
    cache = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    key = hashlib.sha256(os.fsencode(store.root)).hexdigest()
    path = cache / "cherries" / "locks" / (key + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


class LocalStore:
    """Records in a source repository's cherries/runs directory."""

    remote = False

    def __init__(self, repo: Path, project_id: str | None = None) -> None:
        self.repo = Path(
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(repo),
                    "rev-parse",
                    "--show-toplevel",
                ],
                text=True,
            ).strip()
        )
        self.root = self.repo / "cherries"
        self.project_id = project_id or self.repo.name

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def runs(self, *, unfinished: bool = False) -> list[RunRecord]:
        return _runs(self, self.runs_dir, unfinished=unfinished)

    def get(self, run: str | Path) -> RunRecord:
        return _get(self, [self.runs_dir], run)

    def git(self, project_id: str) -> Path:  # noqa: ARG002 - common store interface
        return self.repo

    def gc(self, *, dry_run: bool = False) -> dict[str, int]:
        return _git.gc(self.repo, dry_run=dry_run)


class RemoteStore:
    """A mounted remote root shared by projects with one extensionless CAS."""

    remote = True

    def __init__(self, root: Path, project_id: str | None = None) -> None:
        self.root = root.resolve()
        self.project_id = project_id

    @property
    def runs_dir(self) -> Path:
        if self.project_id is None:
            raise ValueError("A project ID is required for a project runs directory")
        return self.root / "projects" / self.project_id / "runs"

    def runs(self, *, unfinished: bool = False) -> list[RunRecord]:
        if self.project_id is not None:
            return _runs(self, self.runs_dir, unfinished=unfinished)
        return [
            run
            for directory in (self.root / "projects").glob("*/runs")
            for run in _runs(self, directory, unfinished=unfinished)
        ]

    def get(self, run: str | Path) -> RunRecord:
        directories = (
            [self.runs_dir]
            if self.project_id is not None
            else list((self.root / "projects").glob("*/runs"))
        )
        return _get(self, directories, run)

    def git(self, project_id: str) -> Path:
        return self.root / "projects" / project_id / (project_id + ".git")

    def object(self, oid: str) -> Path:
        return self.root / "objects" / "sha256" / oid[:2] / oid[2:4] / oid

    def put(self, source: Path, expected: tuple[str, int] | None = None) -> Path:
        oid, size = expected or identity(source)
        target = self.object(oid)
        if target.exists():
            # Existing content-addressed objects are reused by identity and size.
            # Explicit verify checks their bytes; insertion does not rehash them.
            if not target.is_file() or target.stat().st_size != size:
                raise ValueError(f"CAS object size mismatch: {target}")
        else:
            try:
                _checked_copy(source, target, (oid, size))
            except BaseException:
                _prune_empty(target.parent, self.root)
                raise
        return target

    def gc(self, *, dry_run: bool = False) -> dict[str, int]:
        with _write_lock(self):
            retained = set()
            # Validate every manifest before deleting anything, including unfinished
            # records and records belonging to projects outside this store selection.
            for metadata in (self.root / "projects").glob("*/runs/" + _RUN_PATTERN):
                data = read_yaml(metadata)
                artifacts = artifact_entries(data)
                RunRecord(metadata.parent, self)._verify_metadata(data)
                retained.update(entry["sha256"] for entry in artifacts.values())
            objects = self.root / "objects" / "sha256"
            unreferenced = [
                path
                for path in objects.glob("*/*/*")
                if path.is_file() and path.name not in retained
            ]
            result = {
                "objects": len(unreferenced),
                "bytes": sum(path.stat().st_size for path in unreferenced),
            }
            if not dry_run:
                for path in unreferenced:
                    path.unlink()
                for bucket in [
                    *sorted(objects.glob("*/*")),
                    *sorted(objects.glob("*")),
                    objects,
                    objects.parent,
                ]:
                    if bucket.is_dir() and not any(bucket.iterdir()):
                        bucket.rmdir()
            for repo in (self.root / "projects").glob("*/*.git"):
                counts = _git.gc(repo, dry_run=dry_run)
                for key in result:
                    result[key] += counts[key]
            return result


def _runs(
    store: LocalStore | RemoteStore,
    directory: Path,
    *,
    unfinished: bool,
) -> list[RunRecord]:
    return [
        RunRecord(path.parent, store)
        for path in directory.glob(_RUN_PATTERN)
        if path.parent.name.endswith(".tmp") == unfinished
    ]


def _find_run(directory: Path, name: str) -> Path | None:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise FileNotFoundError(name)
    matches = [
        day / name
        for day in directory.glob(_DATE_PATTERN)
        if (day / name / "run.yaml").is_file()
    ]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous run ID: {name}")
    return next(iter(matches), None)


def _get(
    store: LocalStore | RemoteStore, directories: Sequence[Path], run: str | Path
) -> RunRecord:
    candidate = Path(run)
    if candidate.is_dir():
        return RunRecord(candidate.resolve(), store)
    matches = [path for root in directories if (path := _find_run(root, str(run)))]
    if not matches:
        raise FileNotFoundError(run)
    if len(matches) > 1:
        raise ValueError(f"Ambiguous run ID: {run}")
    return RunRecord(matches[0], store)


def _prune_empty(directory: Path, boundary: Path) -> None:
    """Remove only empty ancestors inside a store, leaving its root intact."""
    while directory != boundary and directory.is_relative_to(boundary):
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            if error.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                break
            raise
        directory = directory.parent


@dataclass
class RunRecord:
    """One run's authoritative metadata and logical files."""

    directory: Path
    store: LocalStore | RemoteStore

    @property
    def metadata(self) -> dict[str, Any]:
        return read_yaml(self.directory / "run.yaml")

    @property
    def id(self) -> str:
        return self.metadata["run-id"]

    def _entries(self, metadata: Mapping[str, Any] | None = None) -> dict[Path, Path]:
        artifacts = artifact_entries(self.metadata if metadata is None else metadata)
        entries = {
            path.relative_to(self.directory): path
            for path in self.directory.rglob("*")
            if path.is_file()
            and path.relative_to(self.directory).parts[0] not in DATA_DIRS
        }
        entries.update(
            {
                name: (
                    self.store.object(entry["sha256"])
                    if isinstance(self.store, RemoteStore)
                    else self.directory / name
                )
                for name, entry in artifacts.items()
            }
        )
        return entries

    def files(self, path: str = "") -> list[str]:
        selected = Path(path)
        return sorted(
            name.as_posix()
            for name in self._entries()
            if name == selected or selected in name.parents
        )

    def _copy_file(
        self, source: Path, destination: Path, entry: Mapping[str, Any] | None
    ) -> Path:
        if entry is not None:
            return _checked_copy(source, destination, (entry["sha256"], entry["size"]))
        return copy(source, destination)

    def get(self, path: str, destination: Path, *, overwrite: bool = False) -> Path:
        destination = destination.resolve()
        selected = Path(path)
        metadata = self.metadata
        artifacts = artifact_entries(metadata)
        entries = self._entries(metadata)
        if selected in entries:
            if destination.exists() and not overwrite:
                raise FileExistsError(destination)
            return self._copy_file(
                entries[selected], destination, artifacts.get(selected)
            )
        planned = [
            (name, source, destination / name.relative_to(selected))
            for name, source in entries.items()
            if selected in name.parents
        ]
        if not planned:
            raise FileNotFoundError(self.directory / selected)
        if not overwrite:
            for _, _, target in planned:
                if target.exists():
                    raise FileExistsError(target)
        # Validate the complete selection before publishing any output file.
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".cherries-", dir=destination.parent
        ) as staging:
            for name, source, _ in planned:
                self._copy_file(
                    source,
                    Path(staging) / name.relative_to(selected),
                    artifacts.get(name),
                )
            for name, _, target in planned:
                copy(Path(staging) / name.relative_to(selected), target)
        return destination

    def edit(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        clear_description: bool = False,
        add_tags: Sequence[str] = (),
        remove_tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        unset_metadata: Sequence[str] = (),
    ) -> Path:
        with _write_lock(self.store):
            data = self.metadata
            if name is not None:
                data["run-name"] = name
            if description is not None:
                data["description"] = description
            if clear_description:
                data.pop("description", None)
            data["tags"] = list(
                dict.fromkeys(
                    [
                        *(tag for tag in data["tags"] if tag not in remove_tags),
                        *add_tags,
                    ]
                )
            )
            data["metadata"].update(metadata or {})
            for key in unset_metadata:
                data["metadata"].pop(key, None)
            write_yaml(self.directory / "run.yaml", data)
            return self.directory

    def add(self, source: Path, target: str) -> Path:
        with _write_lock(self.store):
            logical = Path(target)
            if (
                not logical.parts
                or logical.is_absolute()
                or ".." in logical.parts
                or logical.as_posix() != target
                or not mutable(target)
            ):
                raise ValueError(
                    f"Execution files are fixed or target is invalid: {target}"
                )
            source = source.resolve()
            if logical.parts[0] != "figs":
                return copy(source, self.directory / logical)
            if len(logical.parts) < 2:
                raise ValueError("Figure target must include a relative file name")
            data = self.metadata
            artifact_entries(data)
            records = collect_artifacts(source, Path(*logical.parts[1:]))
            merged = {entry["name"]: entry for entry in data["artifacts"]["figs"]}
            merged.update({entry["name"]: entry for entry in records})
            data["artifacts"]["figs"] = sorted(
                merged.values(), key=lambda entry: entry["name"]
            )
            artifact_entries(data)
            for entry in records:
                name = Path("figs") / entry["name"]
                physical = (
                    source / Path(entry["name"]).relative_to(Path(*logical.parts[1:]))
                    if source.is_dir()
                    else source
                )
                _save_artifact(physical, self, name, entry)
            write_yaml(self.directory / "run.yaml", data)
            return self.directory / logical

    def remove(self) -> None:
        with _write_lock(self.store):
            project_id = self.metadata["project-id"]
            repository = self.store.git(project_id)
            if repository.exists():
                _git.remove(repository, self.id)
            shutil.rmtree(self.directory)
            boundary = (
                self.store.root / "projects" / project_id
                if self.store.remote
                else self.store.root
            )
            _prune_empty(self.directory.parent, boundary)

    def _verify_metadata(self, data: Mapping[str, Any]) -> None:
        """Check metadata and its canonical location without reading payloads."""
        if set(data) - {"description"} != FIELDS:
            raise ValueError(f"Unexpected run.yaml fields: {self.directory}")
        if data["run-id"] != self.directory.name.removesuffix(".tmp"):
            raise ValueError(f"Run ID does not match directory: {self.directory}")
        if not (
            all(
                isinstance(data[key], str)
                for key in ("project-id", "run-id", "run-name")
            )
            and isinstance(data["tags"], list)
            and all(isinstance(tag, str) for tag in data["tags"])
            and isinstance(data["params"], dict)
            and isinstance(data["metadata"], dict)
            and ("description" not in data or isinstance(data["description"], str))
        ):
            raise ValueError("Invalid run.yaml schema")
        for key in ("start-time", "end-time"):
            value = data[key]
            if key == "end-time" and value is None and self.directory.suffix == ".tmp":
                continue
            if (
                not isinstance(value, str)
                or len(value) != 25
                or datetime.strptime(value, "%Y-%m-%d %H:%M:%S%z").isoformat(
                    sep=" ", timespec="seconds"
                )
                != value
            ):
                raise ValueError(f"Invalid {key}: expected YYYY-mm-dd HH:MM:SS±HH:MM")
        runs_dir = (
            self.store.root / "projects" / data["project-id"] / "runs"
            if self.store.remote
            else self.store.runs_dir
        )
        expected = runs_dir / run_relative_path(data["run-id"], data["start-time"])
        if self.directory.suffix == ".tmp":
            expected = expected.with_name(expected.name + ".tmp")
        if self.directory.resolve() != expected.resolve():
            raise ValueError(
                f"Run directory does not match start-time: {self.directory}"
            )

    def verify(self) -> None:  # noqa: C901, PLR0912 - format and source integrity
        data = self.metadata
        self._verify_metadata(data)
        artifacts = artifact_entries(data)
        if self.store.remote:
            for role in DATA_DIRS:
                if (self.directory / role).exists() or (
                    self.directory / role
                ).is_symlink():
                    raise ValueError(f"Disallowed remote artifact directory: {role}")
            for path in self.directory.rglob("*"):
                if path.is_dir() and not any(path.iterdir()):
                    raise ValueError(f"Empty remote run directory: {path}")
        else:
            if any(
                (self.directory / role).exists()
                and not (self.directory / role).is_dir()
                for role in DATA_DIRS
            ):
                raise ValueError("Local artifact roles must be directories")
            actual = {
                path.relative_to(self.directory)
                for role in DATA_DIRS
                for path in (self.directory / role).rglob("*")
                if path.is_file()
            }
            if actual != set(artifacts):
                raise ValueError("Local artifacts are missing or unlisted")
        for name, entry in artifacts.items():
            physical = (
                self.store.object(entry["sha256"])
                if isinstance(self.store, RemoteStore)
                else self.directory / name
            )
            if not physical.is_file() or identity(physical) != (
                entry["sha256"],
                entry["size"],
            ):
                raise ValueError(f"Artifact content mismatch: {name}")
        if not (self.directory / "run.log").is_file():
            raise ValueError(f"Missing run.log: {self.directory}")
        for name, physical in self._entries().items():
            if not (
                name.parts[0] in DATA_DIRS | {"assets", "reports", "src"}
                or name.as_posix()
                in {
                    "run.yaml",
                    "run.log",
                    "metrics.parquet",
                    "README.md",
                    "README.html",
                }
                or (
                    name.as_posix() == "metrics.jsonl"
                    and self.directory.suffix == ".tmp"
                )
            ):
                raise ValueError(f"Unexpected run file: {physical}")
        metrics = self.directory / "metrics.parquet"
        if metrics.exists() and dict(pl.read_parquet_schema(metrics)) != METRIC_SCHEMA:
            raise ValueError(f"Unexpected metric schema: {metrics}")
        repo = self.store.git(data["project-id"])
        if data["commit"] is not None:
            _git.verify(repo, self.id, data["commit"])
            (script,) = (self.directory / "src").iterdir()
            if not script.is_file() or script.suffix != ".py":
                raise ValueError(f"Expected one entry script: {script}")
            paths = (
                subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(repo),
                        "ls-tree",
                        "-r",
                        "--name-only",
                        "-z",
                        data["commit"],
                    ]
                )
                .decode()
                .split("\0")
            )
            if not any(
                Path(path).name == script.name
                and _git.read_file(repo, data["commit"], path) == script.read_bytes()
                for path in paths
                if path
            ):
                raise ValueError(f"Entry script does not match Git snapshot: {script}")
        elif self.directory.suffix != ".tmp":
            raise ValueError("Completed run has no Git commit")


def _checked_copy(source: Path, destination: Path, expected: tuple[str, int]) -> Path:
    """Read the source once, validate destination staging, and publish atomically."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".cherries-", dir=destination.parent
    ) as staging:
        temporary = Path(staging) / "payload"
        copy(source, temporary)
        if identity(temporary) != expected:
            raise ValueError(f"Artifact content mismatch: {source}")
        temporary.replace(destination)
    return destination


def _save_artifact(
    source: Path, run: RunRecord, name: Path, entry: Mapping[str, Any]
) -> Path:
    expected = (entry["sha256"], entry["size"])
    if isinstance(run.store, RemoteStore):
        return run.store.put(source, expected)
    return _checked_copy(source, run.directory / name, expected)


def _sync(
    source: RunRecord,
    destination: RunRecord,
    *,
    overwrite: bool,
) -> None:
    source_data = source.metadata
    artifacts = artifact_entries(source_data)
    entries = source._entries(source_data)
    first = not (destination.directory / "run.yaml").exists()
    data = copying.deepcopy(source_data if first else destination.metadata)
    existing = {} if first else destination._entries(data)
    merged = {entry["name"]: entry for entry in data["artifacts"]["figs"]}
    planned = {
        name: entries[name]
        for name in entries
        if name != Path("run.yaml")
        and (first or (mutable(name) and (overwrite or name not in existing)))
    }
    for name in planned:
        if name in artifacts and name.parts[0] == "figs":
            merged[artifacts[name]["name"]] = artifacts[name]
    data["artifacts"]["figs"] = sorted(merged.values(), key=lambda entry: entry["name"])
    artifact_entries(data)
    # Assets precede figures and reports so relative resources exist first.
    for name in sorted(
        planned, key=lambda p: (p.parts[0] not in {"assets", "figs"}, p.as_posix())
    ):
        if name in artifacts:
            _save_artifact(planned[name], destination, name, artifacts[name])
        else:
            copy(planned[name], destination.directory / name)
    if not first and overwrite:
        for key in _EDITABLE:
            if key in source_data:
                data[key] = source_data[key]
            else:
                data.pop(key, None)
    artifact_entries(data)
    write_yaml(destination.directory / "run.yaml", data)


def _transfer(
    run: RunRecord,
    store: LocalStore | RemoteStore,
    *,
    overwrite: bool,
) -> Path:
    with _write_lock(store):
        metadata = run.metadata
        artifact_entries(metadata)
        source_repo = run.store.git(metadata["project-id"])
        target_repo = store.git(metadata["project-id"])
        runs_dir = (
            store.root / "projects" / metadata["project-id"] / "runs"
            if store.remote
            else store.runs_dir
        )
        existing = _find_run(runs_dir, run.id)
        final = existing or runs_dir / run_relative_path(run.id, metadata["start-time"])
        first = existing is None
        if existing is not None:
            fixed = read_yaml(existing / "run.yaml")
            if (
                fixed["run-id"] != run.id
                or fixed["project-id"] != metadata["project-id"]
            ):
                raise ValueError(f"Run identity does not match destination: {existing}")
        target = final.with_name(final.name + ".tmp") if first else final
        created = not target.exists()
        try:
            target.mkdir(parents=True, exist_ok=True)
            _git.transfer(source_repo, target_repo, run.id)
            _sync(run, RunRecord(target, store), overwrite=overwrite)
            if first:
                target.rename(final)
        except BaseException:
            if created:
                shutil.rmtree(target, ignore_errors=True)
                _prune_empty(target.parent, store.root)
            raise
        return final


def push(run: RunRecord, remote: RemoteStore) -> Path:
    """Copy a local record and source closure, updating only mutable materials."""
    return _transfer(run, remote, overwrite=True)


def pull(run: RunRecord, local: LocalStore, *, overwrite: bool = False) -> Path:
    """Materialize a remote record and import its original refs without checkout."""
    return _transfer(run, local, overwrite=overwrite)

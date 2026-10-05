# Copyright (c) 2026 liblaf
"""A small local CAS for sealed Cherries records.

The on-disk format is intentionally ordinary files: JSON control data and
whole-file SHA-256 objects.  It is suitable for later rclone transport without
requiring a database or a background process.
"""

from __future__ import annotations

import copy
import fcntl
import functools
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class RecordStoreError(RuntimeError):
    """Base error for record-store operations."""


class IntegrityError(RecordStoreError):
    """Raised when an immutable identifier does not match its bytes."""


class NotFoundError(RecordStoreError):
    """Raised when a requested record or object is unavailable."""


class DeletionBlockedError(RecordStoreError):
    """Raised when a destructive operation is not safe."""


def _mutation(method: Any) -> Any:
    @functools.wraps(method)
    def wrapped(self: Store, *args: Any, **kwargs: Any) -> Any:
        with self._mutation_lock():
            return method(self, *args, **kwargs)

    return wrapped


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as file:
        while block := file.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def hash_file(path: Path) -> str:
    """Return the full SHA-256 digest of a regular file."""
    return _file_digest(Path(path))[0]


def canonical_json(value: Any) -> bytes:
    """Encode JSON in the stable representation used for control digests."""
    return _canonical_bytes(value)


def _validate_id(value: Any, name: str = "id") -> str:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        msg = f"invalid {name}: {value!r}"
        raise ValueError(msg)
    return value


def _relative_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value == "."
        or "\\" in value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
        or Path(value).as_posix() != value
    ):
        msg = f"asset path must be relative and contained: {value!r}"
        raise IntegrityError(msg)
    return value


class Store:
    """A local append-only collection of immutable run records.

    ``root`` is a configured data volume, never a temporary system directory.
    The class performs no synchronization by itself; remote publication is a
    separate transport concern.
    """

    format_version = 1

    def __init__(self, root: Path, machine_id: str | None = None) -> None:
        self.root = Path(root)
        self._machine_id = machine_id
        self._collection_id: str | None = None
        self._thread_lock = threading.RLock()
        self._lock_depth = 0
        self._lock_fd: int | None = None
        self._verified_objects: dict[tuple[int, int, int, int, int], str] = {}
        self._control_cache: dict[
            Path, tuple[tuple[int, int, int, int, int], dict[str, Any]]
        ] = {}
        self._control_digests: dict[
            Path, tuple[tuple[int, int, int, int, int], str]
        ] = {}
        self._manifest_indexes: dict[str, tuple[str, dict[str, dict[str, Any]]]] = {}
        self._verified_trees: dict[Path, tuple[int, int, int, int, int]] = {}
        self._event_stamp: tuple[tuple[str, int], ...] = ()
        self._events_by_subject: dict[str, list[dict[str, Any]]] = {}
        self._clock_stamp: tuple[tuple[str, int], ...] | None = None
        self._observed_clock = 0

    @property
    def collection_id(self) -> str:
        self._ensure_readable()
        assert self._collection_id is not None
        return self._collection_id

    @property
    def machine_id(self) -> str:
        self._ensure_readable()
        assert self._machine_id is not None
        return self._machine_id

    def _ensure_readable(self) -> None:
        """Load existing identities without waiting for a long payload writer."""
        if self._collection_id is not None:
            return
        collection_path = self.root / "collection.json"
        machine_path = self.root / "machine.json"
        if not collection_path.is_file() or not machine_path.is_file():
            self.ensure_initialized()
            return
        collection = self._read_json(collection_path)
        machine = self._read_json(machine_path)["machine_id"]
        if self._machine_id is not None and self._machine_id != machine:
            msg = "machine ID does not match existing local store"
            raise IntegrityError(msg)
        self._machine_id = machine
        self._collection_id = collection["collection_id"]

    @_mutation
    def ensure_initialized(self, collection_id: str | None = None) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        for name in (
            "objects/sha256",
            "records",
            "work",
            "runs",
            "metadata/events",
            "pending",
            "attempts",
        ):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        machine_path = self.root / "machine.json"
        if machine_path.exists():
            saved_machine = self._read_json(machine_path)["machine_id"]
            if self._machine_id is not None and self._machine_id != saved_machine:
                msg = "machine ID does not match existing local store"
                raise IntegrityError(msg)
            self._machine_id = saved_machine
        else:
            self._machine_id = self._machine_id or str(uuid.uuid4())
            self._atomic_json(
                machine_path, {"machine_id": self._machine_id, "clock": 0}
            )
        path = self.root / "collection.json"
        if path.exists():
            data = self._read_json(path)
            existing = data["collection_id"]
            if collection_id is not None and collection_id != existing:
                msg = "collection ID does not match existing store"
                raise IntegrityError(msg)
        else:
            data = {
                "format": self.format_version,
                "collection_id": collection_id or str(uuid.uuid4()),
            }
            self._atomic_json(path, data)
        collection_value = data["collection_id"]
        if not isinstance(collection_value, str):
            msg = "collection ID must be a string"
            raise IntegrityError(msg)
        self._collection_id = collection_value
        self._recover_sealed_work()
        return data

    @_mutation
    def start_work(
        self, run_id: str, metadata: Mapping[str, Any] | None = None
    ) -> Path:
        self.ensure_initialized()
        self._assert_no_maintenance()
        run_id = _validate_id(run_id, "run ID")
        if self._record_dir(run_id).exists():
            msg = f"run already sealed: {run_id}"
            raise IntegrityError(msg)
        path = self.root / "work" / run_id
        pending_path = self.root / "pending" / f"{run_id}.json"
        if path.exists():
            if pending_path.exists():
                msg = f"work directory already exists: {run_id}"
                raise IntegrityError(msg)
            receipt = self._read_json(path / ".cherries-work.json")
            if receipt.get("run_id") != run_id:
                msg = f"work directory is not owned by run: {run_id}"
                raise IntegrityError(msg)
            recovered_metadata = receipt.get("metadata")
            if not isinstance(recovered_metadata, dict):
                msg = f"work receipt metadata is invalid: {run_id}"
                raise IntegrityError(msg)
            # A process can die after writing the durable work receipt but
            # before publishing its pending intent.  Recreate only that
            # missing intent; never discard or replace an existing one.
            self._atomic_json(
                pending_path,
                {"run_id": run_id, "roots": [], "metadata": recovered_metadata},
            )
            return path
        if pending_path.exists():
            msg = f"pending intent exists without work directory: {run_id}"
            raise IntegrityError(msg)
        path.mkdir(parents=True)
        work_metadata = dict(metadata or {})
        self._atomic_json(
            path / ".cherries-work.json",
            {"run_id": run_id, "metadata": work_metadata},
        )
        self._atomic_json(
            pending_path,
            {"run_id": run_id, "roots": [], "metadata": work_metadata},
        )
        return path

    @_mutation
    def register_parent(self, child_id: str, parent_id: str) -> None:
        """Register lineage before the child consumes a parent asset."""
        self._assert_no_maintenance()
        child_id, parent_id = _validate_id(child_id), _validate_id(parent_id)
        if child_id == parent_id:
            msg = "a record cannot parent itself"
            raise IntegrityError(msg)
        if (
            not self._record_dir(parent_id).exists()
            and not (self.root / "pending" / f"{parent_id}.json").exists()
        ):
            msg = f"parent record is unknown: {parent_id}"
            raise NotFoundError(msg)
        if self._record_dir(parent_id).exists() and self.is_retired(parent_id):
            msg = f"parent record is retired: {parent_id}"
            raise IntegrityError(msg)
        self._parents_for(parent_id)
        if child_id in self._walk_parents(parent_id):
            msg = "parent relation would create a cycle"
            raise IntegrityError(msg)
        pending = self._pending(child_id)
        pending["parents"] = sorted(set(pending.get("parents", [])) | {parent_id})
        self._atomic_json(self.root / "pending" / f"{child_id}.json", pending)

    @_mutation
    def seal(  # noqa: C901, PLR0915 - sealing is one atomic state transition
        self,
        run_id: str,
        record: Mapping[str, Any],
        work: Path,
        exclude: Iterable[str] = ("scratch",),
    ) -> dict[str, Any]:
        """Store all retained work files as objects and publish immutable metadata."""
        self.ensure_initialized()
        self._assert_no_maintenance()
        run_id = _validate_id(run_id, "run ID")
        work = Path(work).resolve()
        expected = (self.root / "work" / run_id).resolve()
        if work != expected or not work.is_dir():
            msg = "seal requires the store-owned work directory"
            raise IntegrityError(msg)
        if self._record_dir(run_id).exists():
            msg = f"run already sealed: {run_id}"
            raise IntegrityError(msg)
        self._validate_bindings(record)
        ignored = set(exclude) | {".cherries-work.json"}
        files: list[dict[str, Any]] = []
        pending = self._pending(run_id)
        roots = set(pending.get("roots", []))
        for path in sorted(work.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(work).as_posix()
            if relative.split("/", 1)[0] in ignored:
                continue
            if path.is_symlink():
                msg = f"symlink is not a retained asset: {relative}"
                raise IntegrityError(msg)
            digest, size = _file_digest(path)
            asset_id = f"sha256:{digest}"
            roots.add(asset_id)
            self._put_object(path, digest)
            files.append(
                {
                    "path": relative,
                    "asset_id": asset_id,
                    "size": size,
                    "executable": os.access(path, os.X_OK),
                }
            )
        pending["roots"] = sorted(roots)
        self._atomic_json(self.root / "pending" / f"{run_id}.json", pending)
        manifest = {"format": self.format_version, "run_id": run_id, "files": files}
        manifest_digest = _digest_bytes(_canonical_bytes(manifest))
        pending = self._pending(run_id)
        payload = {
            "format": self.format_version,
            "run_id": run_id,
            "collection_id": self.collection_id,
            "machine_id": self.machine_id,
            "record": dict(record),
            "parents": sorted(
                set(pending.get("parents", [])) | set(record.get("parents", []))
            ),
            "manifest_digest": f"sha256:{manifest_digest}",
        }
        for parent in payload["parents"]:
            if parent == run_id or not self._record_dir(parent).exists():
                msg = f"sealed parent is required: {parent}"
                raise IntegrityError(msg)
            if run_id in self._walk_parents(parent):
                msg = "parent relation would create a cycle"
                raise IntegrityError(msg)
        record_digest = _digest_bytes(_canonical_bytes(payload))
        root_digest = _digest_bytes(
            _canonical_bytes({"record": record_digest, "manifest": manifest_digest})
        )
        staging = Path(
            tempfile.mkdtemp(prefix=f".{run_id}.", dir=self.root / "records")
        )
        try:
            self._atomic_json(staging / "manifest.json", manifest)
            self._atomic_json(staging / "record.json", payload)
            self._atomic_json(
                staging / "complete.json",
                {
                    "run_id": run_id,
                    "record_digest": f"sha256:{record_digest}",
                    "manifest_digest": f"sha256:{manifest_digest}",
                    "root_digest": f"sha256:{root_digest}",
                },
            )
            self._fsync_dir(staging)
            staging.replace(self._record_dir(run_id))
            self._fsync_dir(self._record_dir(run_id).parent)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        (self.root / "pending" / f"{run_id}.json").unlink(missing_ok=True)
        shutil.rmtree(work)
        self.append_event("sealed", run_id, {"root_digest": f"sha256:{root_digest}"})
        return {
            "run_id": run_id,
            "record_digest": f"sha256:{record_digest}",
            "manifest_digest": f"sha256:{manifest_digest}",
            "root_digest": f"sha256:{root_digest}",
            "assets": files,
        }

    @_mutation
    def put_tree(self, path: Path) -> str:
        """Store a directory as a deterministic tree and return its tree ID.

        Tree entries refer to the same raw-file objects as a run manifest.  The
        tree descriptor is itself immutable JSON under ``objects/sha256-tree``.
        Callers retain the resulting ID in their record metadata when a bundle,
        rather than one primary file, is an input or output.
        """
        path = Path(path).resolve()
        if not path.is_dir() or path.is_symlink():
            msg = "tree source must be a real directory"
            raise ValueError(msg)
        entries: list[dict[str, Any]] = []
        directories: list[str] = []
        for child in sorted(path.rglob("*")):
            if child.is_symlink():
                msg = f"symlink is not a tree asset: {child}"
                raise IntegrityError(msg)
            if child.is_dir():
                directories.append(child.relative_to(path).as_posix())
                continue
            if not child.is_file():
                continue
            digest, size = _file_digest(child)
            self._put_object(child, digest)
            entries.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "kind": "file",
                    "asset_id": f"sha256:{digest}",
                    "size": size,
                    "executable": os.access(child, os.X_OK),
                }
            )
        descriptor = {
            "format": self.format_version,
            "kind": "cherries-tree",
            "entries": entries,
            "directories": directories,
        }
        data = _canonical_bytes(descriptor)
        digest = _digest_bytes(b"cherries-tree-v1\0" + data)
        target = self.root / "objects" / "sha256-tree" / digest[:2] / digest
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_bytes(target, data)
        elif target.read_bytes() != data:
            msg = f"tree object is corrupt: {digest}"
            raise IntegrityError(msg)
        return f"sha256-tree:{digest}"

    def read_record(self, run_id: str) -> dict[str, Any]:
        directory = self._record_dir(self.resolve_id(run_id))
        expected = self._read_control(directory / "complete.json")["record_digest"]
        return copy.deepcopy(
            self._verified_control(directory / "record.json", expected)
        )

    def read_manifest(self, run_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._read_manifest_cached(run_id))

    def _read_manifest_cached(self, run_id: str) -> dict[str, Any]:
        directory = self._record_dir(self.resolve_id(run_id))
        expected = self._read_control(directory / "complete.json")["manifest_digest"]
        return self._verified_control(directory / "manifest.json", expected)

    def list_records(self) -> list[str]:
        self._ensure_readable()
        return sorted(
            path.name
            for path in (self.root / "records").iterdir()
            if (path / "complete.json").is_file()
        )

    def is_retired(self, run_id: str) -> bool:
        run_id = self.resolve_id(run_id)
        return any(
            event["kind"] == "tombstone" and event["value"].get("value")
            for event in self._events_for(run_id)
        )

    def list_live_records(self) -> list[str]:
        return [run_id for run_id in self.list_records() if not self.is_retired(run_id)]

    def resolve_id(self, prefix: str) -> str:
        _validate_id(prefix, "record ID")
        if self._record_dir(prefix).joinpath("complete.json").is_file():
            return prefix
        matches = [
            run_id for run_id in self.list_records() if run_id.startswith(prefix)
        ]
        if len(matches) != 1:
            msg = f"record prefix must match exactly one record: {prefix}"
            raise NotFoundError(msg)
        return matches[0]

    def resolve_asset(
        self, asset_id: str, source_run: str | None = None
    ) -> dict[str, Any]:
        if asset_id.startswith("sha256-tree:"):
            digest = self._tree_digest(asset_id)
            path = self.root / "objects" / "sha256-tree" / digest[:2] / digest
            if not path.is_file():
                msg = f"tree object unavailable: {asset_id}"
                raise NotFoundError(msg)
            candidates = []
            for run_id in (
                [self.resolve_id(source_run)]
                if source_run
                else self.list_live_records()
            ):
                record = self.read_record(run_id)["record"]
                bindings = [
                    *record.get("bundles", []),
                    *record.get("input_bindings", []),
                ]
                candidates.extend(
                    {
                        **binding,
                        "run_id": run_id,
                        "path": binding.get("staged_path", binding.get("path")),
                    }
                    for binding in bindings
                    if binding.get("asset_id") == asset_id
                )
            result: dict[str, Any] = {
                "asset_id": asset_id,
                "tree": copy.deepcopy(self._read_tree(path, asset_id)),
            }
            if candidates:
                origin = min(
                    candidates, key=lambda item: (item["run_id"], item.get("path", ""))
                )
                result["origin"] = origin
                result["run_id"] = origin["run_id"]
                result["path"] = origin.get("path")
            elif source_run is not None:
                msg = f"tree has no binding in source record: {source_run}"
                raise NotFoundError(msg)
            return result
        digest = self._asset_digest(asset_id)
        candidates: list[dict[str, Any]] = []
        records = (
            [self.resolve_id(source_run)] if source_run else self.list_live_records()
        )
        for run_id in records:
            record_digest = self._read_json(self._record_dir(run_id) / "complete.json")[
                "record_digest"
            ]
            for file in self.read_manifest(run_id)["files"]:
                if file["asset_id"] == f"sha256:{digest}":
                    candidates.append(
                        {**file, "run_id": run_id, "record_digest": record_digest}
                    )
        if not candidates:
            msg = f"asset is not present in a record: {asset_id}"
            raise NotFoundError(msg)
        return min(candidates, key=lambda item: (item["run_id"], item["path"]))

    def materialize_tree(self, asset_id: str, destination: Path) -> Path:
        """Materialize a tree as independent copies beneath ``destination``."""
        descriptor = self.resolve_asset(asset_id)["tree"]
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        for relative in descriptor.get("directories", []):
            directory = destination / relative
            if not directory.resolve().is_relative_to(destination.resolve()):
                msg = "tree destination contains an escaping symlink"
                raise IntegrityError(msg)
            directory.mkdir(parents=True, exist_ok=True)
        for entry in descriptor["entries"]:
            target = destination / entry["path"]
            if not target.resolve().is_relative_to(destination.resolve()):
                msg = "tree destination contains an escaping symlink"
                raise IntegrityError(msg)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._copy_object(entry["asset_id"], target)
            if entry.get("executable"):
                target.chmod(target.stat().st_mode | 0o111)
        return destination

    def object_path(self, asset_id: str) -> Path:
        """Return the local immutable object path, or raise when it is absent."""
        path = self._object_path(self._asset_digest(asset_id))
        if not path.is_file():
            msg = f"object unavailable: {asset_id}"
            raise NotFoundError(msg)
        return path

    def tree_object_path(self, asset_id: str) -> Path:
        """Return a local canonical tree descriptor object."""
        digest = self._tree_digest(asset_id)
        path = self.root / "objects" / "sha256-tree" / digest[:2] / digest
        if not path.is_file():
            msg = f"tree object unavailable: {asset_id}"
            raise NotFoundError(msg)
        return path

    def asset_closure(self, run_id: str) -> list[str]:
        """Return all raw file IDs required by a record, including tree members."""
        run_id = self.resolve_id(run_id)
        ids = {item["asset_id"] for item in self.read_manifest(run_id)["files"]}
        for asset_id in self._asset_ids(self.read_record(run_id)["record"]):
            ids.add(asset_id)
            if asset_id.startswith("sha256-tree:"):
                ids.update(
                    item["asset_id"]
                    for item in self.resolve_asset(asset_id)["tree"]["entries"]
                )
        return sorted(ids)

    @_mutation
    def import_object(self, source: Path, asset_id: str) -> Path:
        """Verify and add a downloaded raw object without trusting transport metadata."""
        digest = self._asset_digest(asset_id)
        if _file_digest(Path(source))[0] != digest:
            msg = f"downloaded object does not match {asset_id}"
            raise IntegrityError(msg)
        self._put_object(Path(source), digest)
        return self._object_path(digest)

    @_mutation
    def import_tree_object(self, source: Path, asset_id: str) -> Path:
        """Verify and add a downloaded versioned tree descriptor."""
        digest = self._tree_digest(asset_id)
        data = Path(source).read_bytes()
        if _digest_bytes(b"cherries-tree-v1\0" + data) != digest:
            msg = f"downloaded tree does not match {asset_id}"
            raise IntegrityError(msg)
        try:
            descriptor = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            msg = "downloaded tree is not valid JSON"
            raise IntegrityError(msg) from error
        self._validate_tree(descriptor)
        if _canonical_bytes(descriptor) != data:
            msg = "downloaded tree is not canonical JSON"
            raise IntegrityError(msg)
        target = self.root / "objects" / "sha256-tree" / digest[:2] / digest
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_bytes(target, data)
        elif target.read_bytes() != data:
            msg = f"tree object is corrupt: {asset_id}"
            raise IntegrityError(msg)
        return target

    @_mutation
    def import_metadata_file(self, relative: Path, data: bytes) -> bool:
        """Atomically import an immutable remote control file under the store lock.

        Returns false when the identical file was already present; a same-name
        different-byte collision is always an integrity failure.
        """
        relative = Path(relative)
        parts = relative.parts
        valid_record = (
            len(parts) == 3
            and parts[0] == "records"
            and parts[2] in {"record.json", "manifest.json", "complete.json"}
        )
        valid_event = (
            len(parts) == 4
            and parts[0:2] == ("metadata", "events")
            and parts[-1].endswith(".json")
        )
        if relative.is_absolute() or ".." in parts or not (valid_record or valid_event):
            msg = f"unsupported immutable metadata path: {relative}"
            raise IntegrityError(msg)
        if valid_event:
            try:
                event = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                msg = "remote metadata event is not valid JSON"
                raise IntegrityError(msg) from error
            allowed = {
                "note",
                "link",
                "recording-incomplete",
                "location-verified",
                "review",
                "label",
                "important",
                "keep-local",
                "hold",
                "tombstone",
                "sealed",
                "execution-failed",
                "local-evicted",
                "location-restored",
                "maintenance-complete",
            }
            if (
                not isinstance(event, dict)
                or not isinstance(event.get("format"), int)
                or isinstance(event.get("format"), bool)
                or event["format"] != self.format_version
                or not isinstance(event.get("kind"), str)
                or event["kind"] not in allowed
                or not isinstance(event.get("event_id"), str)
                or not isinstance(event.get("machine_id"), str)
                or not isinstance(event.get("subject"), str)
                or not isinstance(event.get("clock"), int)
                or isinstance(event.get("clock"), bool)
                or event["clock"] < 0
                or not isinstance(event.get("value"), Mapping)
            ):
                msg = "invalid remote metadata event"
                raise IntegrityError(msg)
            try:
                _validate_id(event["event_id"], "event ID")
                _validate_id(event["machine_id"], "machine ID")
                _validate_id(event["subject"], "event subject")
            except ValueError as error:
                msg = "invalid remote metadata event"
                raise IntegrityError(msg) from error
            if Path(relative).parts[2] != event["machine_id"]:
                msg = "event machine does not match metadata path"
                raise IntegrityError(msg)
            if Path(relative).stem != event["event_id"]:
                msg = "event ID does not match metadata path"
                raise IntegrityError(msg)
        target = self.root / relative
        if target.exists():
            if target.read_bytes() != data:
                msg = f"immutable metadata conflict: {relative}"
                raise IntegrityError(msg)
            return False
        self._atomic_bytes(target, data)
        return True

    @_mutation
    def import_remote_record(  # noqa: C901 - remote receipt checks are one gate
        self,
        record: Mapping[str, Any],
        manifest: Mapping[str, Any],
        complete: Mapping[str, Any],
    ) -> bool:
        """Validate and atomically publish a metadata-only remote record.

        This publishes no payload bytes and therefore never claims local asset
        availability.  Parent receipts must already be present.
        """
        self.ensure_initialized()
        run_id = _validate_id(record.get("run_id", ""), "run ID")
        legacy = (
            isinstance(record.get("record"), Mapping) and "legacy" in record["record"]
        )
        if (
            not isinstance(record.get("format"), int)
            or isinstance(record.get("format"), bool)
            or record["format"] != self.format_version
            or not isinstance(manifest.get("format"), int)
            or isinstance(manifest.get("format"), bool)
            or manifest["format"] != self.format_version
            or not isinstance(record.get("record"), Mapping)
            or not isinstance(record.get("parents"), list)
            or any(not isinstance(parent, str) for parent in record["parents"])
            or (
                not legacy
                and (
                    not isinstance(record.get("machine_id"), str)
                    or not record["machine_id"]
                )
            )
        ):
            msg = "remote record has invalid format or machine identity"
            raise IntegrityError(msg)
        if manifest.get("run_id") != run_id or complete.get("run_id") != run_id:
            msg = "remote record identifiers disagree"
            raise IntegrityError(msg)
        if record.get("collection_id") != self.collection_id:
            msg = "remote record belongs to another collection"
            raise IntegrityError(msg)
        self._validate_files(manifest.get("files"))
        self._validate_bindings(record.get("record", {}))
        record_digest = f"sha256:{_digest_bytes(_canonical_bytes(dict(record)))}"
        manifest_digest = f"sha256:{_digest_bytes(_canonical_bytes(dict(manifest)))}"
        if record.get("manifest_digest") != manifest_digest:
            msg = "remote record does not bind its manifest"
            raise IntegrityError(msg)
        root_digest = f"sha256:{_digest_bytes(_canonical_bytes({'record': record_digest.removeprefix('sha256:'), 'manifest': manifest_digest.removeprefix('sha256:')}))}"
        if (
            complete.get("record_digest") != record_digest
            or complete.get("manifest_digest") != manifest_digest
            or complete.get("root_digest") != root_digest
        ):
            msg = "remote completion digests do not verify"
            raise IntegrityError(msg)
        for parent in record["parents"]:
            _validate_id(parent, "parent ID")
            if (
                parent == run_id
                or not (self._record_dir(parent) / "complete.json").is_file()
            ):
                msg = f"remote parent is not yet imported: {parent}"
                raise IntegrityError(msg)
            self.read_record(parent)
        destination = self._record_dir(run_id)
        if destination.exists():
            for name, value in (
                ("record.json", record),
                ("manifest.json", manifest),
                ("complete.json", complete),
            ):
                if self._read_json(destination / name) != dict(value):
                    msg = f"remote record conflict: {run_id}"
                    raise IntegrityError(msg)
            return False
        staging = Path(
            tempfile.mkdtemp(prefix=f".{run_id}.", dir=self.root / "records")
        )
        try:
            self._atomic_json(staging / "record.json", dict(record))
            self._atomic_json(staging / "manifest.json", dict(manifest))
            self._atomic_json(staging / "complete.json", dict(complete))
            self._fsync_dir(staging)
            staging.replace(destination)
            self._fsync_dir(destination.parent)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return True

    def materialize(
        self, run_id: str, relpath: str, destination: Path | None = None
    ) -> Path:
        run_id = self.resolve_id(run_id)
        if not relpath or Path(relpath).is_absolute() or ".." in Path(relpath).parts:
            msg = "materialized path must be relative and contained"
            raise ValueError(msg)
        manifest = self._read_manifest_cached(run_id)
        manifest_digest = self._read_control(
            self._record_dir(run_id) / "complete.json"
        )["manifest_digest"]
        indexed = self._manifest_indexes.get(run_id)
        if indexed is None or indexed[0] != manifest_digest:
            indexed = (
                manifest_digest,
                {item["path"]: item for item in manifest["files"]},
            )
            self._manifest_indexes[run_id] = indexed
        binding = indexed[1].get(relpath)
        if binding is None:
            msg = f"asset path is not in record: {relpath}"
            raise NotFoundError(msg)
        target = (
            Path(destination)
            if destination is not None
            else self.root / "runs" / run_id / relpath
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        self._copy_object(binding["asset_id"], target)
        if binding.get("executable"):
            target.chmod(target.stat().st_mode | 0o111)
        return target

    @_mutation
    def import_legacy(
        self, path: Path, origin: str, run_id: str | None = None
    ) -> dict[str, Any]:
        """Preserve a legacy folder without claiming it can be replayed."""
        path = Path(path).resolve()
        links = [item for item in path.rglob("*") if item.is_symlink()]
        if links:
            msg = f"legacy import requires an explicit symlink policy: {links[0]}"
            raise IntegrityError(msg)
        run_id = run_id or str(uuid.uuid4())
        self.ensure_initialized()
        if self._record_dir(run_id).exists():
            msg = f"run already sealed: {run_id}"
            raise IntegrityError(msg)
        files: list[dict[str, Any]] = []
        for source in sorted(item for item in path.rglob("*") if item.is_file()):
            digest, size = _file_digest(source)
            self._put_object(source, digest)
            files.append(
                {
                    "path": f"legacy/{source.relative_to(path).as_posix()}",
                    "asset_id": f"sha256:{digest}",
                    "size": size,
                    "executable": os.access(source, os.X_OK),
                }
            )
        manifest = {"format": self.format_version, "run_id": run_id, "files": files}
        manifest_digest = _digest_bytes(_canonical_bytes(manifest))
        payload = {
            "format": self.format_version,
            "run_id": run_id,
            "collection_id": self.collection_id,
            "record": {
                "legacy": {
                    "origin": origin,
                    "provenance": "incomplete",
                    "replay": "unknown",
                    "empty_directories": sorted(
                        item.relative_to(path).as_posix()
                        for item in path.rglob("*")
                        if item.is_dir() and not any(item.iterdir())
                    ),
                }
            },
            "parents": [],
            "manifest_digest": f"sha256:{manifest_digest}",
        }
        record_digest = _digest_bytes(_canonical_bytes(payload))
        root_digest = _digest_bytes(
            _canonical_bytes({"record": record_digest, "manifest": manifest_digest})
        )
        staging = Path(
            tempfile.mkdtemp(prefix=f".{run_id}.", dir=self.root / "records")
        )
        try:
            self._atomic_json(staging / "manifest.json", manifest)
            self._atomic_json(staging / "record.json", payload)
            self._atomic_json(
                staging / "complete.json",
                {
                    "run_id": run_id,
                    "record_digest": f"sha256:{record_digest}",
                    "manifest_digest": f"sha256:{manifest_digest}",
                    "root_digest": f"sha256:{root_digest}",
                },
            )
            self._fsync_dir(staging)
            staging.replace(self._record_dir(run_id))
            self._fsync_dir(self._record_dir(run_id).parent)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {
            "run_id": run_id,
            "record_digest": f"sha256:{record_digest}",
            "manifest_digest": f"sha256:{manifest_digest}",
            "root_digest": f"sha256:{root_digest}",
            "assets": files,
        }

    @_mutation
    def cancel_failed_work(
        self, run_id: str, diagnostics: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Record bounded failure metadata then remove only unsealed owned work."""
        run_id = _validate_id(run_id, "run ID")
        if self._record_dir(run_id).exists():
            msg = "a sealed record cannot be cancelled"
            raise DeletionBlockedError(msg)
        work = self.root / "work" / run_id
        pending = self.root / "pending" / f"{run_id}.json"
        if not work.is_dir() or not pending.is_file():
            msg = f"active work is unavailable: {run_id}"
            raise NotFoundError(msg)
        pending_data = self._read_json(pending)
        pid = pending_data.get("metadata", {}).get("pid")
        if isinstance(pid, int) and pid != os.getpid():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                msg = f"work process is still running: {pid}"
                raise DeletionBlockedError(msg)
        children = [
            path.name.removesuffix(".json")
            for path in (self.root / "pending").glob("*.json")
            if run_id in self._read_json(path).get("parents", [])
        ]
        if children:
            msg = f"unsealed dependent work exists: {sorted(children)}"
            raise DeletionBlockedError(msg)
        protected = [
            kind
            for kind in ("hold", "important")
            if self._active_operations(run_id, kind)
        ]
        protected.extend(
            event["kind"]
            for event in self._events_for(run_id)
            if event["kind"] == "keep-local" and event["value"].get("value")
        )
        if protected:
            msg = f"work has retention events: {sorted(protected)}"
            raise DeletionBlockedError(msg)
        bounded = self._bounded_diagnostics(diagnostics or {})
        attempt = {
            "format": self.format_version,
            "attempt_id": str(uuid.uuid4()),
            "run_id": run_id,
            "machine_id": self.machine_id,
            "status": "execution-failed",
            "diagnostics": bounded,
        }
        self._atomic_json(
            self.root / "attempts" / f"{attempt['attempt_id']}.json", attempt
        )
        event = self.append_event(
            "execution-failed", run_id, {"attempt_id": attempt["attempt_id"]}
        )
        shutil.rmtree(work)
        pending.unlink(missing_ok=True)
        return event

    def list_attempts(self) -> list[dict[str, Any]]:
        self._ensure_readable()
        return [
            self._read_json(path)
            for path in sorted((self.root / "attempts").glob("*.json"))
        ]

    @_mutation
    def append_event(
        self, kind: str, subject: str, value: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        self.ensure_initialized()
        _validate_id(subject, "subject")
        machine_path = self.root / "machine.json"
        machine = self._read_json(machine_path)
        stamp = self._event_directory_stamp()
        if stamp != self._clock_stamp:
            self._observed_clock = max(
                (
                    int(self._read_control(path).get("clock", 0))
                    for path in (self.root / "metadata" / "events").glob("*/*.json")
                ),
                default=0,
            )
        clock = max(int(machine.get("clock", 0)), self._observed_clock) + 1
        machine["clock"] = clock
        self._atomic_json(machine_path, machine)
        event = {
            "format": self.format_version,
            "event_id": str(uuid.uuid4()),
            "machine_id": self.machine_id,
            "clock": clock,
            "kind": kind,
            "subject": subject,
            "value": dict(value or {}),
        }
        path = (
            self.root
            / "metadata"
            / "events"
            / self.machine_id
            / f"{event['event_id']}.json"
        )
        self._atomic_json(path, event)
        self._observed_clock = clock
        self._clock_stamp = self._event_directory_stamp()
        return event

    @_mutation
    def review(self, run_id: str, status: str, note: str = "") -> dict[str, Any]:
        return self.append_event(
            "review", self.resolve_id(run_id), {"status": status, "note": note}
        )

    @_mutation
    def label(self, run_id: str, label: str, *, present: bool = True) -> dict[str, Any]:
        run_id = self.resolve_id(run_id)
        value: dict[str, Any] = {"label": label}
        if present:
            value["operation_id"] = str(uuid.uuid4())
        else:
            value["remove"] = sorted(
                self._active_operations(run_id, "label", "label", label)
            )
        return self.append_event("label", run_id, value)

    @_mutation
    def mark(
        self,
        run_id: str,
        *,
        important: bool | None = None,
        keep_local: bool | None = None,
    ) -> list[dict[str, Any]]:
        run_id = self.resolve_id(run_id)
        events = []
        if important is not None:
            value = (
                {"operation_id": str(uuid.uuid4())}
                if important
                else {"remove": sorted(self._active_operations(run_id, "important"))}
            )
            events.append(self.append_event("important", run_id, value))
        if keep_local is not None:
            events.append(
                self.append_event("keep-local", run_id, {"value": keep_local})
            )
        return events

    @_mutation
    def hold(self, run_id: str, reason: str) -> dict[str, Any]:
        return self.append_event(
            "hold",
            self.resolve_id(run_id),
            {"reason": reason, "operation_id": str(uuid.uuid4())},
        )

    @_mutation
    def release_hold(self, run_id: str, reason: str) -> dict[str, Any]:
        run_id = self.resolve_id(run_id)
        return self.append_event(
            "hold",
            run_id,
            {
                "reason": reason,
                "remove": sorted(
                    self._active_operations(run_id, "hold", "reason", reason)
                ),
            },
        )

    def projection(self, run_id: str) -> dict[str, Any]:
        run_id = self.resolve_id(run_id)
        labels: set[str] = set()
        holds: set[str] = set()
        output: dict[str, Any] = {
            "run_id": run_id,
            "labels": labels,
            "holds": holds,
            "important": False,
            "keep_local": False,
            "reviews": [],
            "notes": [],
            "links": [],
        }
        for event in self._events_for(run_id):
            value = event["value"]
            if event["kind"] == "label" and value.get(
                "operation_id"
            ) in self._active_operations(run_id, "label"):
                labels.add(value["label"])
            elif event["kind"] == "hold" and value.get(
                "operation_id"
            ) in self._active_operations(run_id, "hold"):
                holds.add(value["reason"])
            elif event["kind"] == "important":
                output["important"] = bool(self._active_operations(run_id, "important"))
            elif (
                event["kind"] == "keep-local" and event["machine_id"] == self.machine_id
            ):
                output["keep_local"] = value["value"]
            elif event["kind"] == "review":
                output["reviews"].append(dict(value))
            elif event["kind"] == "note":
                output["notes"].append(dict(value))
            elif event["kind"] == "link":
                output["links"].append(dict(value))
        return output

    def rebuild_index(self) -> dict[str, Any]:
        index = {
            "format": self.format_version,
            "records": {
                run: self._read_json(self._record_dir(run) / "complete.json")[
                    "root_digest"
                ]
                for run in self.list_records()
            },
        }
        self._atomic_json(self.root / "index.json", index)
        return index

    def maintenance_inventory(self) -> dict[str, Any]:
        """Digest every local control root that can affect deletion safety."""
        paths = [self.root / "collection.json", self.root / "machine.json"]
        paths.extend((self.root / "records").glob("*/*.json"))
        paths.extend((self.root / "metadata" / "events").glob("*/*.json"))
        paths.extend((self.root / "attempts").glob("*.json"))
        paths.extend((self.root / "pending").glob("*.json"))
        paths.extend((self.root / "work").glob("*/.cherries-work.json"))
        return {
            "format": self.format_version,
            "entries": {
                str(
                    path.relative_to(self.root)
                ): f"sha256:{_digest_bytes(path.read_bytes())}"
                for path in sorted(paths)
                if path.is_file()
            },
        }

    @_mutation
    def pause_maintenance(self) -> dict[str, Any]:
        """Freeze Store writers and issue a receipt bound to the local inventory."""
        self.ensure_initialized()
        marker = self.root / "maintenance.json"
        if marker.exists():
            msg = "maintenance is already active"
            raise DeletionBlockedError(msg)
        if any((self.root / "pending").glob("*.json")) or any(
            (self.root / "work").iterdir()
        ):
            msg = "active or pending work prevents maintenance"
            raise DeletionBlockedError(msg)
        # Imported legacy records deliberately advertise unknown provenance and
        # cannot authorize destructive lifecycle operations.
        if any(
            "legacy" in self.read_record(run)["record"] for run in self.list_records()
        ):
            msg = "legacy provenance prevents maintenance"
            raise DeletionBlockedError(msg)
        foreign = {
            event["machine_id"]
            for path in (self.root / "metadata" / "events").glob("*/*.json")
            for event in [self._read_json(path)]
            if event["machine_id"] != self.machine_id
        }
        foreign.update(
            record["machine_id"]
            for run in self.list_records()
            for record in [self.read_record(run)]
            if record.get("machine_id") and record["machine_id"] != self.machine_id
        )
        if foreign:
            msg = f"foreign participants require fleet receipts: {sorted(foreign)}"
            raise DeletionBlockedError(msg)
        inventory = self.maintenance_inventory()
        receipt = {
            "machine_id": self.machine_id,
            "token": str(uuid.uuid4()),
            "operation": "maintenance",
            "inventory_digest": f"sha256:{_digest_bytes(_canonical_bytes(inventory))}",
        }
        self._atomic_json(marker, receipt)
        return receipt

    @_mutation
    def resume_maintenance(self, token: str) -> None:
        marker = self.root / "maintenance.json"
        if not marker.exists():
            msg = "maintenance is not active"
            raise DeletionBlockedError(msg)
        receipt = self._read_json(marker)
        if (
            receipt.get("machine_id") != self.machine_id
            or receipt.get("token") != token
        ):
            msg = "maintenance receipt is not owned by this machine"
            raise DeletionBlockedError(msg)
        marker.unlink()

    def _maintenance_receipt(self) -> dict[str, Any]:
        marker = self.root / "maintenance.json"
        if not marker.exists():
            msg = "a local maintenance receipt is required"
            raise DeletionBlockedError(msg)
        receipt = self._read_json(marker)
        if receipt.get("machine_id") != self.machine_id:
            msg = "maintenance receipt belongs to another machine"
            raise DeletionBlockedError(msg)
        return receipt

    def plan_discard(
        self,
        run_id: str,
        *,
        inventory_complete: bool = False,
        maintenance: bool = False,
    ) -> dict[str, Any]:
        self._maintenance_receipt()
        run_id = self.resolve_id(run_id)
        children = [
            child
            for child in self.list_records()
            if run_id in self.read_record(child)["parents"]
        ]
        projection = self.projection(run_id)
        blocked = list(children)
        blocked.extend(sorted(projection["holds"]))
        if projection["important"]:
            blocked.append("important")
        if not (inventory_complete and maintenance):
            blocked = [*children, "inventory or maintenance mode unavailable"]
        return {
            "run_id": run_id,
            "action": "discard",
            "inventory_digest": self._maintenance_receipt()["inventory_digest"],
            "allowed": not bool(blocked),
            "blocked": sorted(blocked),
        }

    @_mutation
    def apply_discard(
        self,
        run_id: str,
        *,
        inventory_complete: bool = False,
        maintenance: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan_discard(
            run_id, inventory_complete=inventory_complete, maintenance=maintenance
        )
        if not plan["allowed"]:
            raise DeletionBlockedError(str(plan["blocked"]))
        current = (
            f"sha256:{_digest_bytes(_canonical_bytes(self.maintenance_inventory()))}"
        )
        if current != plan["inventory_digest"]:
            msg = "inventory changed since maintenance pause"
            raise DeletionBlockedError(msg)
        self.append_event("tombstone", plan["run_id"], {"value": True})
        return plan

    def plan_prune(
        self, *, inventory_complete: bool = False, maintenance: bool = False
    ) -> dict[str, Any]:
        if not (inventory_complete and maintenance):
            return {
                "allowed": False,
                "blocked": ["inventory or maintenance mode unavailable"],
                "objects": [],
            }
        rooted = {
            file["asset_id"]
            for run in self.list_live_records()
            for file in self.read_manifest(run)["files"]
        }
        for run in self.list_live_records():
            for asset_id in self._asset_ids(self.read_record(run)["record"]):
                rooted.add(asset_id)
                if asset_id.startswith("sha256-tree:"):
                    rooted.update(
                        entry["asset_id"]
                        for entry in self.resolve_asset(asset_id)["tree"]["entries"]
                    )
        pending = list((self.root / "pending").glob("*.json"))
        if pending:
            return {
                "allowed": False,
                "blocked": ["pending intents exist"],
                "objects": [],
            }
        objects = [
            path
            for path in (self.root / "objects" / "sha256").glob("*/*")
            if f"sha256:{path.name}" not in rooted
        ]
        return {
            "allowed": True,
            "blocked": [],
            "objects": [str(path.relative_to(self.root)) for path in objects],
        }

    @_mutation
    def apply_prune(
        self, *, inventory_complete: bool = False, maintenance: bool = False
    ) -> dict[str, Any]:
        self._maintenance_receipt()
        # The flock and marker freeze reference creators, so this second
        # inventory is the exact root set used for deletion.
        plan = self.plan_prune(
            inventory_complete=inventory_complete, maintenance=maintenance
        )
        if not plan["allowed"]:
            raise DeletionBlockedError(str(plan["blocked"]))
        receipt = self._maintenance_receipt()
        inventory_digest = (
            f"sha256:{_digest_bytes(_canonical_bytes(self.maintenance_inventory()))}"
        )
        if inventory_digest != receipt["inventory_digest"]:
            msg = "inventory changed since maintenance pause"
            raise DeletionBlockedError(msg)
        for relative in plan["objects"]:
            (self.root / relative).unlink()
        self.append_event("maintenance-complete", "collection", {"operation": "prune"})
        return plan

    @_mutation
    def evict_local(  # noqa: C901, PLR0912 - all roots must be checked before any unlink
        self, run_id: str, *, remote_verified: bool
    ) -> dict[str, Any]:
        """Evict verified remote payload bytes that no local root still needs."""
        run_id = self.resolve_id(run_id)
        blocked: list[str] = []
        if not remote_verified:
            blocked.append("remote-not-verified")
        state = self.projection(run_id)
        if state["keep_local"]:
            blocked.append("keep-local")
        if state["holds"]:
            blocked.append("holds")
        if (self.root / "pending" / f"{run_id}.json").exists():
            blocked.append("active-work-or-pending-intent")
        if blocked:
            return {
                "run_id": run_id,
                "allowed": False,
                "blocked": blocked,
                "evicted": [],
            }
        view = self.root / "runs" / run_id
        if view.exists():
            shutil.rmtree(view)
            evicted = [str(view.relative_to(self.root))]
        else:
            evicted = []
        protected = {
            asset_id
            for other in self.list_live_records()
            if other != run_id
            and (
                self._is_locally_resident(other)
                or self.projection(other)["holds"]
                or self.projection(other)["keep_local"]
            )
            for asset_id in self.asset_closure(other)
        }
        for pending in (self.root / "pending").glob("*.json"):
            for asset_id in self._read_json(pending).get("roots", []):
                protected.add(asset_id)
                if asset_id.startswith("sha256-tree:"):
                    protected.update(
                        item["asset_id"]
                        for item in self.resolve_asset(asset_id)["tree"]["entries"]
                    )
        for asset_id in self.asset_closure(run_id):
            if asset_id in protected or asset_id.startswith("sha256-tree:"):
                continue
            path = self._object_path(self._asset_digest(asset_id))
            if path.exists():
                path.unlink()
                evicted.append(str(path.relative_to(self.root)))
        self.append_event(
            "local-evicted", run_id, {"remote_verified": True, "items": evicted}
        )
        return {"run_id": run_id, "allowed": True, "blocked": [], "evicted": evicted}

    def _record_dir(self, run_id: str) -> Path:
        return self.root / "records" / run_id

    def _recover_sealed_work(self) -> None:
        """Remove only owned work left behind after a published seal crashed."""
        candidates = {
            path.name.removesuffix(".json")
            for path in (self.root / "pending").glob("*.json")
        }
        candidates.update(
            path.name
            for path in (self.root / "work").iterdir()
            if path.is_dir() and not path.is_symlink()
        )
        for run_id in candidates:
            try:
                _validate_id(run_id, "run ID")
            except ValueError:
                continue
            if not (self._record_dir(run_id) / "complete.json").is_file():
                continue
            work = self.root / "work" / run_id
            if not self._owned_dead_work(work, run_id):
                continue
            # Verify the published receipt before treating its abandoned
            # staging directory as disposable.  Unreadable, malformed, or
            # unavailable payload remains visible for recovery.
            try:
                self._verify_published_payload(run_id)
            except (
                FileNotFoundError,
                IntegrityError,
                KeyError,
                NotFoundError,
                ValueError,
                json.JSONDecodeError,
            ):
                continue
            (self.root / "pending" / f"{run_id}.json").unlink(missing_ok=True)
            if work.exists():
                shutil.rmtree(work)

    def _owned_dead_work(self, work: Path, run_id: str) -> bool:
        if not work.exists():
            return True
        if not work.is_dir() or work.is_symlink():
            return False
        try:
            receipt = self._read_json(work / ".cherries-work.json")
        except (json.JSONDecodeError, NotFoundError):
            return False
        return receipt.get("run_id") == run_id and not self._work_process_is_alive(
            receipt
        )

    @staticmethod
    def _work_process_is_alive(receipt: Mapping[str, Any]) -> bool:
        metadata = receipt.get("metadata", {})
        if not isinstance(metadata, Mapping):
            return False
        pid = metadata.get("pid")
        if not isinstance(pid, int):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _verify_published_payload(self, run_id: str) -> None:
        """Verify a sealed control root and every locally retained payload byte."""
        directory = self._record_dir(run_id)
        complete = self._read_control(directory / "complete.json")
        record = self.read_record(run_id)
        manifest = self.read_manifest(run_id)
        record_digest = complete.get("record_digest")
        manifest_digest = complete.get("manifest_digest")
        if (
            complete.get("run_id") != run_id
            or not isinstance(record_digest, str)
            or not isinstance(manifest_digest, str)
            or record.get("manifest_digest") != manifest_digest
        ):
            msg = f"published record is structurally invalid: {run_id}"
            raise IntegrityError(msg)
        record_hash = self._asset_digest(record_digest)
        manifest_hash = self._asset_digest(manifest_digest)
        root_digest = f"sha256:{_digest_bytes(_canonical_bytes({'record': record_hash, 'manifest': manifest_hash}))}"
        if complete.get("root_digest") != root_digest:
            msg = f"published root digest does not verify: {run_id}"
            raise IntegrityError(msg)
        for entry in manifest["files"]:
            self._verify_object(entry["asset_id"], entry["size"])
        for asset_id in self._asset_ids(record["record"]):
            if asset_id.startswith("sha256-tree:"):
                digest = self._tree_digest(asset_id)
                descriptor = self._read_tree(
                    self.root / "objects" / "sha256-tree" / digest[:2] / digest,
                    asset_id,
                )
                for entry in descriptor["entries"]:
                    self._verify_object(entry["asset_id"], entry["size"])
            else:
                self._verify_object(asset_id)

    def _verify_object(self, asset_id: str, size: int | None = None) -> None:
        digest = self._asset_digest(asset_id)
        path = self._object_path(digest)
        if not path.is_file():
            msg = f"object unavailable: {asset_id}"
            raise NotFoundError(msg)
        actual_digest, actual_size = _file_digest(path)
        if actual_digest != digest or (size is not None and actual_size != size):
            msg = f"CAS object bytes do not match asset ID: {asset_id}"
            raise IntegrityError(msg)

    @contextmanager
    def _mutation_lock(self) -> Any:
        """Hold one advisory lock over a complete root state transition."""
        with self._thread_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            if self._lock_depth == 0:
                lock_path = self.root / ".store.lock"
                self._lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
                if self._lock_depth == 0:
                    assert self._lock_fd is not None
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                    os.close(self._lock_fd)
                    self._lock_fd = None

    def _assert_no_maintenance(self) -> None:
        marker = self.root / "maintenance.json"
        if marker.exists():
            msg = "collection is in maintenance; reference creation is frozen"
            raise DeletionBlockedError(msg)

    def _object_path(self, digest: str) -> Path:
        return self.root / "objects" / "sha256" / digest[:2] / digest

    def _asset_digest(self, asset_id: str) -> str:
        prefix, separator, digest = asset_id.partition(":")
        if (
            prefix != "sha256"
            or not separator
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            msg = f"invalid asset ID: {asset_id}"
            raise ValueError(msg)
        return digest

    def _tree_digest(self, asset_id: str) -> str:
        prefix, separator, digest = asset_id.partition(":")
        if (
            prefix != "sha256-tree"
            or not separator
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            msg = f"invalid tree asset ID: {asset_id}"
            raise ValueError(msg)
        return digest

    def _put_object(self, source: Path, digest: str) -> None:
        target = self._object_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stat = target.stat()
            identity = (
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            )
            if (
                self._verified_objects.get(identity) != digest
                and _file_digest(target)[0] != digest
            ):
                msg = f"existing object is corrupt: {digest}"
                raise IntegrityError(msg)
            self._verified_objects[identity] = digest
            return
        fd, temp_name = tempfile.mkstemp(prefix=f".{digest}.", dir=target.parent)
        try:
            with source.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
                try:
                    # FICLONE is copy-on-write on Linux filesystems such as Btrfs.
                    # It still creates an independent inode, never a writable link.
                    fcntl.ioctl(outgoing.fileno(), 0x40049409, incoming.fileno())
                except OSError:
                    incoming.seek(0)
                    shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if _file_digest(Path(temp_name))[0] != digest:
                msg = "object changed while sealing"
                raise IntegrityError(msg)
            Path(temp_name).replace(target)
            self._fsync_dir(target.parent)
            stat = target.stat()
            self._verified_objects[
                (
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                )
            ] = digest
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _copy_object(self, asset_id: str, destination: Path) -> None:
        expected = self._asset_digest(asset_id)
        source = self._object_path(expected)
        if not source.is_file():
            msg = f"object unavailable: {asset_id}"
            raise NotFoundError(msg)
        fd, temp_name = tempfile.mkstemp(prefix=".materialize.", dir=destination.parent)
        try:
            with source.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
                try:
                    fcntl.ioctl(outgoing.fileno(), 0x40049409, incoming.fileno())
                except OSError:
                    outgoing.seek(0)
                    outgoing.truncate()
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if hash_file(Path(temp_name)) != expected:
                msg = f"CAS object bytes do not match asset ID: {asset_id}"
                raise IntegrityError(msg)
            Path(temp_name).replace(destination)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _pending(self, run_id: str) -> dict[str, Any]:
        path = self.root / "pending" / f"{run_id}.json"
        if not path.exists():
            msg = f"no active work for run: {run_id}"
            raise NotFoundError(msg)
        return self._read_json(path)

    def _parents_for(self, run_id: str) -> list[str]:
        return (
            self.read_record(run_id).get("parents", [])
            if self._record_dir(run_id).exists()
            else self._pending(run_id).get("parents", [])
        )

    def _walk_parents(self, run_id: str) -> set[str]:
        seen: set[str] = set()
        todo = [run_id]
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            todo.extend(self._parents_for(current))
        return seen

    def _events_for(self, run_id: str) -> list[dict[str, Any]]:
        events_root = self.root / "metadata" / "events"
        stamp = self._event_directory_stamp()
        if stamp != self._event_stamp:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for path in events_root.glob("*/*.json"):
                event = self._read_control(path)
                grouped.setdefault(event.get("subject", ""), []).append(event)
            self._events_by_subject = {
                subject: sorted(
                    items,
                    key=lambda event: (
                        event.get("clock", 0),
                        event["machine_id"],
                        event["event_id"],
                    ),
                )
                for subject, items in grouped.items()
            }
            self._event_stamp = stamp
        return self._events_by_subject.get(run_id, [])

    def _event_directory_stamp(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            sorted(
                (path.name, path.stat().st_mtime_ns)
                for path in (self.root / "metadata" / "events").iterdir()
                if path.is_dir()
            )
        )

    def _is_locally_resident(self, run_id: str) -> bool:
        locations = [
            event
            for event in self._events_for(run_id)
            if event["kind"] in {"local-evicted", "location-restored"}
            and event["machine_id"] == self.machine_id
        ]
        return not locations or locations[-1]["kind"] == "location-restored"

    def _validate_files(self, entries: Any) -> None:
        if not isinstance(entries, list):
            msg = "asset entries must be a list"
            raise IntegrityError(msg)
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                msg = "asset entry must be an object"
                raise IntegrityError(msg)

            relative = _relative_path(entry.get("path"))
            if relative in seen:
                msg = f"duplicate asset path: {relative}"
                raise IntegrityError(msg)
            seen.add(relative)
            self._asset_digest(entry.get("asset_id", ""))
            if (
                not isinstance(entry.get("size"), int)
                or isinstance(entry.get("size"), bool)
                or entry["size"] < 0
            ):
                msg = "asset size must be a nonnegative integer"
                raise IntegrityError(msg)

    def _validate_bindings(self, record: Mapping[str, Any]) -> None:
        bundles = record.get("bundles", [])
        input_bindings = record.get("input_bindings", [])
        if not isinstance(bundles, list) or not isinstance(input_bindings, list):
            msg = "asset bindings must be lists"
            raise IntegrityError(msg)
        for binding in [*bundles, *input_bindings]:
            if not isinstance(binding, Mapping):
                msg = "asset binding must be an object"
                raise IntegrityError(msg)
            destination = binding.get("staged_path", binding.get("path"))
            if destination is not None:
                _relative_path(destination)

    def _validate_tree(self, descriptor: Any) -> None:
        if (
            not isinstance(descriptor, Mapping)
            or not isinstance(descriptor.get("format"), int)
            or isinstance(descriptor.get("format"), bool)
            or descriptor["format"] != self.format_version
            or descriptor.get("kind") != "cherries-tree"
        ):
            msg = "tree has an unsupported descriptor"
            raise IntegrityError(msg)
        self._validate_files(descriptor.get("entries"))
        files = {entry["path"] for entry in descriptor["entries"]}
        directories = descriptor.get("directories", [])
        if (
            not isinstance(directories, list)
            or any(not isinstance(item, str) for item in directories)
            or len(set(directories)) != len(directories)
        ):
            msg = "tree directories must be a unique list"
            raise IntegrityError(msg)
        for directory in directories:
            relative = _relative_path(directory)
            if relative in files:
                msg = f"tree path is both a file and directory: {relative}"
                raise IntegrityError(msg)

    def _read_tree(self, path: Path, asset_id: str) -> dict[str, Any]:
        stat = path.stat()
        identity = (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
        descriptor = self._read_control(path)
        if self._verified_trees.get(path) != identity:
            data = path.read_bytes()
            if (
                _digest_bytes(b"cherries-tree-v1\0" + data)
                != self._tree_digest(asset_id)
                or _canonical_bytes(descriptor) != data
            ):
                msg = f"tree object is corrupt: {asset_id}"
                raise IntegrityError(msg)
            self._validate_tree(descriptor)
            self._verified_trees[path] = identity
        return descriptor

    def _active_operations(
        self, run_id: str, kind: str, field: str | None = None, value: str | None = None
    ) -> set[str]:
        events = [event for event in self._events_for(run_id) if event["kind"] == kind]
        removed = {
            operation
            for event in events
            for operation in event["value"].get("remove", [])
        }
        return {
            event["value"]["operation_id"]
            for event in events
            if "operation_id" in event["value"]
            and event["value"]["operation_id"] not in removed
            and (field is None or event["value"].get(field) == value)
        }

    @staticmethod
    def _asset_ids(value: Any) -> set[str]:
        if isinstance(value, str) and (value.startswith(("sha256:", "sha256-tree:"))):
            return {value}
        if isinstance(value, Mapping):
            return set().union(*(Store._asset_ids(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(Store._asset_ids(item) for item in value))
        return set()

    @staticmethod
    def _bounded_diagnostics(value: Mapping[str, Any]) -> dict[str, Any]:
        """Keep failure receipts readable and small even for a huge traceback."""
        encoded = _canonical_bytes(dict(value))
        if len(encoded) <= 16_384:
            return dict(value)
        return {
            "truncated": True,
            "sha256": f"sha256:{_digest_bytes(encoded)}",
            "tail": encoded[-8192:].decode(errors="replace"),
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_bytes())
        except FileNotFoundError as error:
            raise NotFoundError(str(path)) from error

    @staticmethod
    def _stat_identity(path: Path) -> tuple[int, int, int, int, int]:
        stat = path.stat()
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    def _read_control(self, path: Path) -> dict[str, Any]:
        identity = self._stat_identity(path)
        cached = self._control_cache.get(path)
        if cached is not None and cached[0] == identity:
            return cached[1]
        value = self._read_json(path)
        self._control_cache[path] = (identity, value)
        self._control_digests[path] = (
            identity,
            f"sha256:{_digest_bytes(_canonical_bytes(value))}",
        )
        return value

    def _verified_control(self, path: Path, expected: str) -> dict[str, Any]:
        value = self._read_control(path)
        if self._control_digests[path][1] != expected:
            msg = f"control digest mismatch: {path}"
            raise IntegrityError(msg)
        return value

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        descriptor = os.open(path, os.O_DIRECTORY)
        os.fsync(descriptor)
        os.close(descriptor)

    def _atomic_json(self, path: Path, value: Mapping[str, Any]) -> None:
        self._atomic_bytes(path, _canonical_bytes(value))

    def _atomic_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            Path(temp_name).replace(path)
            self._fsync_dir(path.parent)
        finally:
            Path(temp_name).unlink(missing_ok=True)

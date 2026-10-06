# Copyright (c) 2026 liblaf
# ruff: noqa: C901, EM101, EM102, PLR0912, PLR0915, TRY003
"""Foreground transport for immutable Cherries CAS publications.

This module intentionally supports only a local directory backend by itself.  A
non-local rclone destination requires an externally coordinated publisher; rclone
has no portable create-if-absent operation, so this module never claims that a
local lock protects a cloud remote.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liblaf.cherries.records import record_asset_ids


class RemoteError(RuntimeError):
    """A foreground archive transport failed."""


class RemoteCapabilityError(RemoteError):
    """The requested remote cannot provide the required publication boundary."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _is_sha256_id(value: Any) -> bool:
    """Return whether ``value`` is a complete lowercase SHA-256 asset ID."""
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _is_receipt(value: Any) -> bool:
    """Return whether a checkpoint or commit has all receipt digest proofs."""
    return isinstance(value, Mapping) and all(
        _is_sha256_id(value.get(field))
        for field in ("record_digest", "manifest_digest", "root_digest")
    )


def _is_contained_id(value: Any) -> bool:
    """Return whether ``value`` is safe to use as one metadata path component."""
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and Path(value).name == value
    )


def _as_local(remote: str | Path) -> Path | None:
    value = str(remote)
    if value.startswith("file://"):
        return Path(value.removeprefix("file://"))
    if ":" not in value:
        return Path(value)
    return None


def _object_path(root: Path, digest: str) -> Path:
    return root / "objects" / "sha256" / digest[:2] / digest


def _metadata_path(root: Path, relative: Path) -> Path:
    return root / relative


def _atomic_copy(source: Path, destination: Path, expected: str) -> None:
    """Copy ``source`` once, or prove an immutable destination is identical."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != expected:
            raise IntegrityError(f"remote object differs: {destination}")
        return

    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as temporary:
        temp = Path(temporary.name)
        with source.open("rb") as input_file:
            shutil.copyfileobj(input_file, temporary)
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        try:
            os.link(temp, destination)
        except FileExistsError:
            if sha256_file(destination) != expected:
                raise IntegrityError(f"remote object differs: {destination}") from None
        if sha256_file(destination) != expected:
            raise IntegrityError(f"read-back hash differs: {destination}")
    finally:
        temp.unlink(missing_ok=True)


class IntegrityError(RemoteError):
    """Bytes at a content-addressed destination did not match their digest."""


_EVENT_KINDS = frozenset(
    {
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
)


@dataclass(frozen=True)
class RemoteLocation:
    remote: str
    run_id: str
    commit: str


class Remote:
    """A small immutable-object publisher.

    ``remote`` may be a local directory, which is suitable for tests and for a
    filesystem with a real shared administration boundary.  Other values are
    rclone paths.  They require ``coordinated=True`` as an explicit statement
    that a real external publisher serializes this collection; it is never
    substituted with a local marker or flock.
    """

    def __init__(
        self, remote: str | Path, *, rclone: str = "rclone", coordinated: bool = False
    ) -> None:
        self.remote = str(remote)
        self.local = _as_local(remote)
        self.rclone = rclone
        self.coordinated = coordinated

    def _require_publish_coordination(self) -> None:
        if self.local is None and not self.coordinated:
            raise RemoteCapabilityError(
                "generic rclone publication requires explicit external coordination"
            )

    def _remote_name(self, relative: Path) -> str:
        return f"{self.remote.rstrip('/')}/{relative.as_posix()}"

    def _rclone_bytes(self, relative: Path) -> bytes:
        process = subprocess.run(
            [self.rclone, "cat", self._remote_name(relative)],
            check=False,
            capture_output=True,
        )
        if process.returncode:
            raise RemoteError(process.stderr.decode(errors="replace").strip())
        return process.stdout

    def _publish(self, source: Path, relative: Path, digest: str) -> None:
        if self.local is not None:
            _atomic_copy(source, _metadata_path(self.local, relative), digest)
            return
        self._require_publish_coordination()
        try:
            existing = self._rclone_bytes(relative)
        except RemoteError:
            existing = None
        if existing is not None:
            if hashlib.sha256(existing).hexdigest() != digest:
                raise IntegrityError(f"remote object differs: {relative}")
            return
        process = subprocess.run(
            [
                self.rclone,
                "copyto",
                "--immutable",
                str(source),
                self._remote_name(relative),
            ],
            check=False,
            capture_output=True,
        )
        if process.returncode:
            # A concurrent immutable publisher may have won.  Read-back decides.
            try:
                actual = hashlib.sha256(self._rclone_bytes(relative)).hexdigest()
            except RemoteError as error:
                raise RemoteError(
                    process.stderr.decode(errors="replace").strip()
                ) from error
            if actual != digest:
                raise IntegrityError(f"remote object differs: {relative}")
            return
        if hashlib.sha256(self._rclone_bytes(relative)).hexdigest() != digest:
            raise IntegrityError(f"read-back hash differs: {relative}")

    def _fetch(self, relative: Path, destination: Path, digest: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.local is not None:
            source = _metadata_path(self.local, relative)
            if not source.is_file():
                raise RemoteError(f"remote file missing: {relative}")
            _atomic_copy(source, destination, digest)
            return
        process = subprocess.run(
            [self.rclone, "copyto", self._remote_name(relative), str(destination)],
            check=False,
            capture_output=True,
        )
        if process.returncode:
            raise RemoteError(process.stderr.decode(errors="replace").strip())
        if sha256_file(destination) != digest:
            destination.unlink(missing_ok=True)
            raise IntegrityError(f"download hash differs: {relative}")

    @staticmethod
    def _assets(manifest: Mapping[str, Any]) -> set[str]:
        values: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, str) and value.startswith("sha256-tree:"):
                raise RemoteCapabilityError("tree-object archive is not implemented")
            if isinstance(value, str) and value.startswith("sha256:"):
                values.add(value.removeprefix("sha256:"))
            elif isinstance(value, Mapping):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(manifest)
        return values

    @staticmethod
    def _find_object(root: Path, digest: str) -> Path:
        direct = _object_path(root, digest)
        if direct.is_file():
            return direct
        matches = (
            list((root / "objects").rglob(digest))
            if (root / "objects").exists()
            else []
        )
        if len(matches) == 1 and matches[0].is_file():
            return matches[0]
        raise RemoteError(f"local CAS object missing or ambiguous: sha256:{digest}")

    def archive(self, store: Any, run_id: str) -> RemoteLocation:
        """Publish a complete immutable run; the commit marker is written last."""
        run_id = str(store.resolve_id(run_id))
        root = Path(store.root)
        # Make the complete parent graph browseable before this child commit;
        # the checkpoint deliberately makes no payload-availability claim.
        self.sync_metadata(root)
        asset_ids = list(store.asset_closure(run_id))
        raw_assets = [item for item in asset_ids if item.startswith("sha256:")]
        tree_assets = [item for item in asset_ids if item.startswith("sha256-tree:")]
        if len(raw_assets) + len(tree_assets) != len(asset_ids):
            raise RemoteCapabilityError("record closure contains an unknown asset type")
        for asset_id in raw_assets:
            digest = asset_id.removeprefix("sha256:")
            source = store.object_path(asset_id)
            if sha256_file(source) != digest:
                raise IntegrityError(f"local object differs: {asset_id}")
            self._publish(
                source, Path("objects") / "sha256" / digest[:2] / digest, digest
            )
        for asset_id in tree_assets:
            digest = asset_id.removeprefix("sha256-tree:")
            source = store.tree_object_path(asset_id)
            data = source.read_bytes()
            if hashlib.sha256(b"cherries-tree-v1\0" + data).hexdigest() != digest:
                raise IntegrityError(f"local tree object differs: {asset_id}")
            self._publish(
                source,
                Path("objects") / "sha256-tree" / digest[:2] / digest,
                sha256_file(source),
            )

        record_dir = root / "records" / run_id
        if not record_dir.is_dir():
            raise RemoteError(f"record metadata missing: {run_id}")
        for name in ("record.json", "manifest.json", "complete.json"):
            source = record_dir / name
            if source.is_file():
                self._publish(
                    source, Path("records") / run_id / name, sha256_file(source)
                )

        native_complete = json.loads((record_dir / "complete.json").read_text())
        closure = sorted(asset_ids)
        commit_payload = {
            "schema": "cherries-remote-commit-v1",
            "run_id": run_id,
            "record_digest": native_complete["record_digest"],
            "manifest_digest": native_complete["manifest_digest"],
            "root_digest": native_complete["root_digest"],
            "closure": closure,
        }
        encoded = (
            json.dumps(commit_payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        commit = hashlib.sha256(encoded).hexdigest()
        with tempfile.NamedTemporaryFile("wb", delete=False) as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
            temporary = Path(file.name)
        try:
            # The remote-only commit is last. Native complete.json remains intact.
            self._publish(temporary, Path("records") / run_id / "commit.json", commit)
        finally:
            temporary.unlink(missing_ok=True)
        return RemoteLocation(self.remote, run_id, commit)

    def _metadata_bytes(self, relative: Path) -> bytes:
        if self.local is not None:
            source = _metadata_path(self.local, relative)
            if not source.is_file():
                message = f"remote file missing: {relative}"
                raise RemoteError(message)
            return source.read_bytes()
        return self._rclone_bytes(relative)

    def _remote_files(self, relative: Path) -> list[Path]:
        """List remote metadata only; it never enumerates payload objects."""
        if self.local is not None:
            root = self.local / relative
            return (
                [
                    path.relative_to(self.local)
                    for path in root.rglob("*")
                    if path.is_file()
                ]
                if root.exists()
                else []
            )
        process = subprocess.run(
            [
                self.rclone,
                "lsf",
                "--files-only",
                "--recursive",
                self._remote_name(relative),
            ],
            check=False,
            capture_output=True,
        )
        if process.returncode:
            raise RemoteError(process.stderr.decode(errors="replace").strip())
        return [
            relative / line for line in process.stdout.decode().splitlines() if line
        ]

    @staticmethod
    def _write_immutable(destination: Path, data: bytes) -> bool:
        """Install bytes once; reject same-name divergent remote metadata."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != data:
                raise IntegrityError(f"metadata conflict: {destination}")
            return False
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
            temporary = Path(file.name)
        try:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != data:
                    raise IntegrityError(f"metadata conflict: {destination}") from None
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)

    def list_remote_records(self) -> list[str]:
        commits = self._remote_files(Path("records"))
        return sorted(
            path.parent.name for path in commits if path.name == "commit.json"
        )

    def import_metadata(self, store: Any, run_id: str | None = None) -> dict[str, int]:
        """Import committed payload records and payload-free checkpoints safely."""
        checkpoint_records: dict[str, Mapping[str, str]] = {}
        checkpoint_events: dict[Path, str] = {}
        collection_missing = False
        try:
            collection = json.loads(
                self._metadata_bytes(Path("metadata") / "collection.json")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IntegrityError("remote collection metadata is invalid") from error
        except RemoteError:
            collection_missing = True
            collection = None
        if not collection_missing and (
            not isinstance(collection, Mapping)
            or collection.get("collection_id") != store.collection_id
        ):
            raise IntegrityError("remote metadata belongs to a different collection")
        # Selected imports still need a proof for a metadata-only record and
        # its ancestor controls.  Checkpoints are compact control evidence;
        # reading them never fetches payload bytes.
        for path in self._remote_files(Path("metadata") / "checkpoints"):
            if path.suffix != ".json":
                continue
            raw = self._metadata_bytes(path)
            digest = path.stem
            if hashlib.sha256(raw).hexdigest() != digest:
                raise IntegrityError("metadata checkpoint name does not match bytes")
            try:
                checkpoint = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise IntegrityError("metadata checkpoint is invalid") from error
            checkpoint_format = (
                checkpoint.get("format") if isinstance(checkpoint, Mapping) else None
            )
            if (
                not isinstance(checkpoint, Mapping)
                or _canonical_json(checkpoint) != raw
                or not isinstance(checkpoint_format, int)
                or isinstance(checkpoint_format, bool)
                or checkpoint_format != 1
                or checkpoint.get("kind") != "cherries-metadata-checkpoint"
                or checkpoint.get("collection_id") != store.collection_id
            ):
                raise IntegrityError("metadata checkpoint is invalid")
            record_proofs = checkpoint.get("records")
            if not isinstance(record_proofs, Mapping):
                raise IntegrityError("metadata checkpoint records are invalid")
            for identifier, proof in record_proofs.items():
                if not _is_contained_id(identifier) or not _is_receipt(proof):
                    raise IntegrityError("metadata checkpoint records are invalid")
                if (
                    identifier in checkpoint_records
                    and checkpoint_records[identifier] != proof
                ):
                    raise IntegrityError(
                        "metadata checkpoints disagree on a record receipt"
                    )
                checkpoint_records[identifier] = proof
            event_proofs = checkpoint.get("events", {})
            if not isinstance(event_proofs, Mapping):
                raise IntegrityError("metadata checkpoint events are invalid")
            for name, proof in event_proofs.items():
                relative = Path(name) if isinstance(name, str) else Path()
                parts = relative.parts
                valid_path = (
                    not relative.is_absolute()
                    and ".." not in parts
                    and len(parts) == 4
                    and parts[:2] == ("metadata", "events")
                    and relative.name.endswith(".json")
                    and relative.as_posix() == name
                )
                digest = proof.removeprefix("sha256:") if isinstance(proof, str) else ""
                if not valid_path or (
                    not isinstance(proof, str)
                    or not proof.startswith("sha256:")
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                ):
                    raise IntegrityError("metadata checkpoint event proof is invalid")
                if (
                    relative in checkpoint_events
                    and checkpoint_events[relative] != proof
                ):
                    raise IntegrityError("metadata checkpoints disagree on an event")
                checkpoint_events[relative] = proof
        verified_events: list[tuple[Path, bytes]] = []
        # Validate every checkpoint-bound event before installing any record
        # metadata.  A checkpoint is a single publication boundary, so a bad
        # event must not leave its otherwise-valid records partially imported.
        for remote_path, proof in sorted(checkpoint_events.items()):
            data = self._metadata_bytes(remote_path)
            if hashlib.sha256(data).hexdigest() != proof.removeprefix("sha256:"):
                raise IntegrityError("remote event does not match its checkpoint")
            try:
                event = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise IntegrityError("remote event is invalid") from error
            if not isinstance(event, Mapping):
                raise IntegrityError("remote event is invalid")
            clock = event.get("clock")
            kind = event.get("kind")
            subject = event.get("subject")
            if (
                not isinstance(event.get("format"), int)
                or isinstance(event.get("format"), bool)
                or event["format"] != getattr(store, "format_version", 1)
                or not isinstance(kind, str)
                or kind not in _EVENT_KINDS
                or isinstance(clock, bool)
                or not isinstance(clock, int)
                or clock < 0
                or not isinstance(event.get("value"), Mapping)
                or not isinstance(subject, str)
                or not subject
                or subject in {".", ".."}
                or "/" in subject
                or "\\" in subject
                or event.get("event_id") != remote_path.stem
                or event.get("machine_id") != remote_path.parts[2]
            ):
                raise IntegrityError("remote event is invalid")
            verified_events.append((remote_path, data))
        candidates = (
            {run_id}
            if run_id
            else set(self.list_remote_records()) | set(checkpoint_records)
        )
        pending: dict[str, dict[str, Any]] = {}
        todo = list(candidates)
        while todo:
            candidate = todo.pop()
            if candidate in pending:
                continue
            if not candidate or Path(candidate).name != candidate:
                raise RemoteError("remote record ID is not contained")
            payloads = {
                name: self._metadata_bytes(Path("records") / candidate / name)
                for name in ("record.json", "manifest.json", "complete.json")
            }
            try:
                record, manifest, complete = (
                    json.loads(payloads[name])
                    for name in ("record.json", "manifest.json", "complete.json")
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise IntegrityError("remote record metadata is invalid") from error
            if not all(
                isinstance(value, Mapping) for value in (record, manifest, complete)
            ):
                raise IntegrityError("remote record metadata is invalid")
            if record.get("collection_id") != store.collection_id:
                raise IntegrityError("remote record belongs to a different collection")
            parents = record.get("parents", [])
            if not isinstance(parents, list) or any(
                not _is_contained_id(parent) for parent in parents
            ):
                raise IntegrityError("remote record metadata is invalid")
            expected = checkpoint_records.get(candidate)
            commit_path = Path("records") / candidate / "commit.json"
            commit_missing = False
            try:
                commit = json.loads(self._metadata_bytes(commit_path))
            except RemoteError:
                commit_missing = True
                commit = None
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise IntegrityError("remote commit marker is invalid") from error
            if not commit_missing:
                if (
                    not isinstance(commit, Mapping)
                    or commit.get("schema") != "cherries-remote-commit-v1"
                    or commit.get("run_id") != candidate
                    or not _is_receipt(commit)
                    or not isinstance(commit.get("closure"), list)
                ):
                    raise IntegrityError("remote commit marker is invalid")
                self._closure_ids(commit["closure"])
                expected = {
                    key: commit.get(key)
                    for key in ("record_digest", "manifest_digest", "root_digest")
                }
            if expected is None:
                raise IntegrityError(
                    "remote record has no checkpoint or complete marker"
                )
            if any(
                complete.get(key) != expected.get(key)
                for key in ("record_digest", "manifest_digest", "root_digest")
            ):
                raise IntegrityError("remote receipt does not match its checkpoint")
            pending[candidate] = {
                "record": record,
                "manifest": manifest,
                "complete": complete,
            }
            if run_id is not None:
                todo.extend(
                    parent
                    for parent in parents
                    if parent not in pending and parent not in set(store.list_records())
                )
        records = 0
        known = set(store.list_records())
        while pending:
            ready = [
                identifier
                for identifier, data in pending.items()
                if set(data["record"].get("parents", [])) <= known
            ]
            if not ready:
                raise IntegrityError("remote records have unresolved or cyclic parents")
            for identifier in ready:
                data = pending.pop(identifier)
                records += store.import_remote_record(
                    data["record"], data["manifest"], data["complete"]
                )
                known.add(identifier)
        # Marker-last checkpoints are the publication boundary for event
        # metadata too.  Files copied before a new checkpoint are ordinary
        # in-progress publication state and are deliberately ignored.
        events = 0
        for remote_path, data in verified_events:
            events += store.import_metadata_file(remote_path, data)
        return {"records": records, "events": events}

    def _fetch_raw_to_store(self, store: Any, asset_id: str) -> Path:
        digest = asset_id.removeprefix("sha256:")
        with tempfile.NamedTemporaryFile(dir=Path(store.root), delete=False) as file:
            temporary = Path(file.name)
        temporary.unlink()
        try:
            self._fetch(
                Path("objects") / "sha256" / digest[:2] / digest, temporary, digest
            )
            return Path(store.import_object(temporary, asset_id))
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_closure_asset(asset_id: Any) -> str:
        """Reject a malformed asset before using it as a remote object path."""
        if not isinstance(asset_id, str):
            raise IntegrityError("remote commit has an invalid object closure")
        if asset_id.startswith("sha256-tree:"):
            digest = asset_id.removeprefix("sha256-tree:")
        elif asset_id.startswith("sha256:"):
            digest = asset_id.removeprefix("sha256:")
        else:
            raise IntegrityError("remote commit has an unknown asset type")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise IntegrityError("remote commit has an invalid object digest")
        return asset_id

    @classmethod
    def _closure_ids(cls, closure: Any) -> set[str]:
        """Validate a canonical commit closure before it gates metadata import."""
        if (
            not isinstance(closure, list)
            or any(not isinstance(asset_id, str) for asset_id in closure)
            or closure != sorted(closure)
            or len(closure) != len(set(closure))
        ):
            raise IntegrityError("remote commit has an invalid object closure")
        return {cls._validate_closure_asset(asset_id) for asset_id in closure}

    def _fetch_tree_to_store(self, store: Any, tree_id: str) -> Path:
        """Fetch and validate one tree descriptor without materializing its files."""
        digest = tree_id.removeprefix("sha256-tree:")
        data = self._metadata_bytes(
            Path("objects") / "sha256-tree" / digest[:2] / digest
        )
        with tempfile.NamedTemporaryFile(dir=Path(store.root), delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
        try:
            return Path(store.import_tree_object(temporary, tree_id))
        finally:
            temporary.unlink(missing_ok=True)

    def fetch_asset(self, store: Any, run_id: str, relpath: str) -> Path:
        """Download exactly one manifest-selected object before materialization."""
        run_id = str(store.resolve_id(run_id))
        binding = next(
            (
                item
                for item in store.read_manifest(run_id).get("files", [])
                if item["path"] == relpath
            ),
            None,
        )
        if binding is None:
            raise RemoteError(f"asset path is not in record: {relpath}")
        digest = binding["asset_id"].removeprefix("sha256:")
        if len(digest) != 64:
            raise IntegrityError("manifest contains an invalid asset ID")
        self._fetch_raw_to_store(store, binding["asset_id"])
        return Path(store.materialize(run_id, relpath))

    def fetch_tree(self, store: Any, tree_id: str, destination: Path) -> Path:
        """Fetch a declared bundle descriptor and every declared companion."""
        digest = tree_id.removeprefix("sha256-tree:")
        if not tree_id.startswith("sha256-tree:") or len(digest) != 64:
            raise RemoteError("tree ID must be a complete sha256-tree ID")
        self._fetch_tree_to_store(store, tree_id)
        descriptor = store.resolve_asset(tree_id)["tree"]
        for entry in descriptor["entries"]:
            self._fetch_raw_to_store(store, entry["asset_id"])
        return Path(store.materialize_tree(tree_id, destination))

    def restore(self, store: Any, run_id: str) -> Path:
        """Fetch a committed closure, verify every object, and materialize copies."""
        run_id = str(run_id)
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise RemoteError("restore requires an exact contained run ID")
        try:
            commit = json.loads(
                self._metadata_bytes(Path("records") / run_id / "commit.json")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IntegrityError("remote commit marker is invalid") from error
        if (
            not isinstance(commit, Mapping)
            or commit.get("schema") != "cherries-remote-commit-v1"
            or commit.get("run_id") != run_id
            or not _is_receipt(commit)
            or not isinstance(commit.get("closure"), list)
        ):
            raise IntegrityError("remote commit marker does not identify requested run")
        closure_ids = self._closure_ids(commit["closure"])
        reader_reason = f"restore:{uuid.uuid4()}"
        # Metadata enters only through Store's locked immutable importer.
        # A child commit may be the only payload archived.  Import the
        # checkpointed control graph first so Store can validate its parents;
        # this still does not assert that an ancestor's payload is remote.
        self.import_metadata(store)
        store.hold(run_id, reader_reason)
        try:
            root = Path(store.root)
            record_dir = root / "records" / run_id
            complete = json.loads((record_dir / "complete.json").read_text())
            record = json.loads((record_dir / "record.json").read_text())
            manifest = json.loads((record_dir / "manifest.json").read_text())
            record_digest = (
                f"sha256:{hashlib.sha256(_canonical_json(record)).hexdigest()}"
            )
            manifest_digest = (
                f"sha256:{hashlib.sha256(_canonical_json(manifest)).hexdigest()}"
            )
            root_digest = f"sha256:{hashlib.sha256(_canonical_json({'record': record_digest.removeprefix('sha256:'), 'manifest': manifest_digest.removeprefix('sha256:')})).hexdigest()}"
            expected = {
                "record_digest": record_digest,
                "manifest_digest": manifest_digest,
                "root_digest": root_digest,
            }
            for field, value in expected.items():
                if complete.get(field) != value or commit.get(field) != value:
                    raise IntegrityError(f"remote commit does not bind native {field}")
            declared_assets = {
                *(item["asset_id"] for item in manifest.get("files", [])),
                *record_asset_ids(record.get("record", {})),
            }
            if not declared_assets <= closure_ids:
                raise IntegrityError("remote commit has an incomplete object closure")
            # A descriptor has to be present before Store can expand the full
            # tree closure.  Check the exact expansion before fetching any raw
            # bytes, so a forged marker cannot materialize a partial run or
            # induce downloads of unrelated remote objects.
            for asset_id in sorted(
                asset for asset in declared_assets if asset.startswith("sha256-tree:")
            ):
                self._fetch_tree_to_store(store, asset_id)
            expected_closure = set(store.asset_closure(run_id))
            if closure_ids != expected_closure:
                raise IntegrityError("remote commit has an incomplete object closure")
            for asset_id in sorted(expected_closure):
                if asset_id.startswith("sha256:"):
                    self._fetch_raw_to_store(store, asset_id)
            output = root / "runs" / run_id
            for file in manifest.get("files", []):
                store.materialize(run_id, file["path"])
            for binding in [
                *record.get("record", {}).get("bundles", []),
                *record.get("record", {}).get("input_bindings", []),
            ]:
                asset_id = binding.get("asset_id", "")
                relative = binding.get("staged_path", binding.get("path"))
                if isinstance(relative, str) and asset_id.startswith("sha256-tree:"):
                    store.materialize_tree(asset_id, output / relative)
            store.append_event(
                "location-restored", run_id, {"remote": self.remote, "complete": True}
            )
            return output
        finally:
            store.release_hold(run_id, reader_reason)

    def sync_metadata(self, root: Path) -> int:
        """Publish control evidence and a marker-last, payload-free checkpoint."""
        root = Path(root)
        collection = root / "collection.json"
        if not collection.is_file():
            raise RemoteError("local collection metadata is unavailable")
        collection_data = json.loads(collection.read_text())
        collection_id = collection_data.get("collection_id")
        if not isinstance(collection_id, str):
            raise IntegrityError("local collection metadata is invalid")
        self._publish(
            collection, Path("metadata") / "collection.json", sha256_file(collection)
        )
        count = 1
        events = root / "metadata" / "events"
        event_digests: dict[str, str] = {}
        for source in sorted(events.rglob("*.json")) if events.exists() else []:
            relative = Path("metadata") / source.relative_to(root / "metadata")
            digest = sha256_file(source)
            self._publish(source, relative, digest)
            event_digests[relative.as_posix()] = f"sha256:{digest}"
            count += 1
        records = root / "records"
        inventory: dict[str, dict[str, str]] = {}
        if records.exists():
            for record_dir in sorted(records.iterdir()):
                complete = record_dir / "complete.json"
                if not complete.is_file():
                    continue
                complete_data = json.loads(complete.read_text())
                inventory[record_dir.name] = {
                    key: complete_data[key]
                    for key in ("record_digest", "manifest_digest", "root_digest")
                }
                for name in ("record.json", "manifest.json", "complete.json"):
                    source = record_dir / name
                    if not source.is_file():
                        raise IntegrityError(
                            f"sealed record control is incomplete: {record_dir.name}"
                        )
                    self._publish(
                        source,
                        Path("records") / record_dir.name / name,
                        sha256_file(source),
                    )
                    count += 1
        checkpoint = {
            "format": 1,
            "kind": "cherries-metadata-checkpoint",
            "collection_id": collection_id,
            "records": inventory,
            "events": event_digests,
        }
        data = _canonical_json(checkpoint)
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.NamedTemporaryFile("wb", delete=False) as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
            temporary = Path(file.name)
        try:
            # This marker claims metadata completeness only. It never carries a
            # payload closure and therefore never establishes remote availability.
            self._publish(
                temporary, Path("metadata") / "checkpoints" / f"{digest}.json", digest
            )
        finally:
            temporary.unlink(missing_ok=True)
        return count + 1

# Copyright (c) 2026 liblaf
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries._remote import IntegrityError, Remote
from liblaf.cherries.records import canonical_json


class StoreForRemote:
    def __init__(
        self,
        root: Path,
        run_id: str,
        record: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        self.root = root
        self.run_id = run_id
        self._record = record
        self._manifest = manifest
        self.collection_id = "collection"

    def resolve_id(self, run_id: str) -> str:
        assert run_id == self.run_id
        return run_id

    def read_record(self, run_id: str) -> dict[str, Any]:
        assert run_id == self.run_id
        return self._record

    def read_manifest(self, run_id: str) -> dict[str, Any]:
        assert run_id == self.run_id
        return self._manifest

    def asset_closure(self, run_id: str) -> list[str]:
        assert run_id == self.run_id
        return [item["asset_id"] for item in self._manifest["files"]]  # type: ignore[index]

    def object_path(self, asset_id: str) -> Path:
        return object_path(self.root, asset_id.removeprefix("sha256:"))

    def list_records(self) -> list[str]:
        return [self.run_id]

    def import_remote_record(
        self,
        record: dict[str, Any],
        manifest: dict[str, Any],
        complete: dict[str, Any],
    ) -> bool:
        self._record = record
        self._manifest = manifest
        directory = self.root / "records" / self.run_id
        directory.mkdir(parents=True, exist_ok=True)
        for name, value in (
            ("record.json", record),
            ("manifest.json", manifest),
            ("complete.json", complete),
        ):
            (directory / name).write_text(json.dumps(value))
        return True

    def import_metadata_file(self, relative: Path, data: bytes) -> bool:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return False
        target.write_bytes(data)
        return True

    def import_object(self, source: Path, asset_id: str) -> Path:
        target = self.object_path(asset_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return target

    def materialize(self, run_id: str, relpath: str) -> Path:
        assert run_id == self.run_id
        path = self.root / "runs" / run_id / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def hold(self, run_id: str, _reason: str) -> None:
        assert run_id == self.run_id

    def release_hold(self, run_id: str, _reason: str) -> None:
        assert run_id == self.run_id

    def append_event(self, kind: str, run_id: str, _value: dict[str, Any]) -> None:
        assert kind == "location-restored"
        assert run_id == self.run_id


def object_path(root: Path, digest: str) -> Path:
    return root / "objects" / "sha256" / digest[:2] / digest


def make_store(tmp_path: Path) -> tuple[StoreForRemote, str, bytes]:
    run_id = "run-1"
    data = b"immutable payload\n"
    digest = hashlib.sha256(data).hexdigest()
    source = object_path(tmp_path, digest)
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    manifest: dict[str, Any] = {
        "files": [{"path": "outputs/result.txt", "asset_id": f"sha256:{digest}"}]
    }
    # Match the on-disk v1 control root used by Store.  Remote archive first
    # publishes this collection evidence and must not need a product fallback.
    (tmp_path / "collection.json").write_text(
        json.dumps({"format": 1, "collection_id": "collection"})
    )
    record: dict[str, Any] = {
        "format": 1,
        "run_id": run_id,
        "collection_id": "collection",
        "record": {},
        "parents": [],
        "manifest_digest": "",
    }
    record_dir = tmp_path / "records" / run_id
    record_dir.mkdir(parents=True)
    manifest_digest = hashlib.sha256(canonical_json(manifest)).hexdigest()
    record["manifest_digest"] = f"sha256:{manifest_digest}"
    record_digest = hashlib.sha256(canonical_json(record)).hexdigest()
    (record_dir / "record.json").write_text(json.dumps(record))
    (record_dir / "manifest.json").write_text(json.dumps(manifest))
    root_digest = hashlib.sha256(
        canonical_json({"record": record_digest, "manifest": manifest_digest})
    ).hexdigest()
    (record_dir / "complete.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "record_digest": f"sha256:{record_digest}",
                "manifest_digest": f"sha256:{manifest_digest}",
                "root_digest": f"sha256:{root_digest}",
            }
        )
    )
    return StoreForRemote(tmp_path, run_id, record, manifest), digest, data


def test_local_remote_archives_objects_before_complete_marker(tmp_path: Path) -> None:
    store, digest, data = make_store(tmp_path / "local")
    remote_root = tmp_path / "remote"

    location = Remote(remote_root).archive(store, "run-1")

    assert (
        remote_root / "objects" / "sha256" / digest[:2] / digest
    ).read_bytes() == data
    complete = json.loads(
        (remote_root / "records" / "run-1" / "commit.json").read_text()
    )
    assert complete["run_id"] == "run-1"
    assert location.run_id == "run-1"


def test_archive_rejects_existing_object_with_wrong_bytes(tmp_path: Path) -> None:
    store, digest, _ = make_store(tmp_path / "local")
    remote_root = tmp_path / "remote"
    target = object_path(remote_root, digest)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"wrong")

    with pytest.raises(IntegrityError, match="differs"):
        Remote(remote_root).archive(store, "run-1")


def test_generic_rclone_allows_readers_but_requires_publication_coordination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"x")
    with pytest.raises(Exception, match="explicit external coordination"):
        Remote("cloud:cherries")._publish(  # noqa: SLF001
            source, Path("object"), hashlib.sha256(b"x").hexdigest()
        )


def test_local_remote_restore_fetches_verified_object_closure(tmp_path: Path) -> None:
    source, digest, data = make_store(tmp_path / "source")
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run-1")
    restored = StoreForRemote(tmp_path / "restored", "run-1", {}, {})

    path = Remote(remote_root).restore(restored, "run-1")

    assert path == tmp_path / "restored" / "runs" / "run-1"
    assert object_path(tmp_path / "restored", digest).read_bytes() == data


def test_restore_rejects_commit_with_an_incomplete_object_closure(
    tmp_path: Path,
) -> None:
    """A commit must bind every asset before restore mutates a local view."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run")
    commit_path = remote_root / "records" / "run" / "commit.json"
    commit = json.loads(commit_path.read_text())
    commit["closure"] = []
    commit_path.write_text(json.dumps(commit))

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="object closure"):
        Remote(remote_root).restore(target, "run")
    assert not list((target.root / "runs" / "run").rglob("*"))


def test_restore_into_fresh_actual_store(tmp_path: Path) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "outputs").mkdir()
    (work / "outputs" / "result.txt").write_text("verified\n")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run")

    restored = Store(tmp_path / "restored")
    restored.ensure_initialized("collection")
    path = Remote(remote_root).restore(restored, "run")

    assert (path / "outputs" / "result.txt").read_text() == "verified\n"


def test_metadata_import_and_selected_asset_fetch_without_full_restore(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "a.txt").write_text("a")
    (work / "b.txt").write_text("b")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)
    remote.archive(source, "run")

    target = Store(tmp_path / "target")
    target.ensure_initialized("collection")
    # The sealed receipt is a control event; it is synchronized with the
    # metadata checkpoint even though no payload is restored.
    assert remote.import_metadata(target) == {"records": 1, "events": 1}
    selected = remote.fetch_asset(target, "run", "a.txt")

    assert selected.read_text() == "a"
    assert not (tmp_path / "target" / "runs" / "run" / "b.txt").exists()


def test_metadata_import_merges_two_machine_event_files(tmp_path: Path) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    source.label("run", "first")
    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)
    remote.archive(source, "run")
    remote.sync_metadata(source.root)

    other = Store(tmp_path / "other", machine_id="machine-b")
    other.ensure_initialized("collection")
    merged = remote.import_metadata(other)
    assert merged["records"] == 1
    assert merged["events"] >= 1
    assert other.projection("run")["labels"] == {"first"}


def test_archive_and_restore_transitive_tree_closure(tmp_path: Path) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source")
    source.ensure_initialized("collection")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "frame-0.vtk").write_text("frame")
    tree_id = source.put_tree(bundle)
    work = source.start_work("run")
    (work / "receipt.txt").write_text("receipt")
    source.seal("run", {"bundle": tree_id}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run")

    target = Store(tmp_path / "target")
    target.ensure_initialized("collection")
    Remote(remote_root).restore(target, "run")

    assert target.tree_object_path(tree_id).is_file()
    materialized = target.materialize_tree(tree_id, tmp_path / "tree-view")
    assert (materialized / "frame-0.vtk").read_text() == "frame"


def test_remote_restore_materializes_bound_empty_tree_directories(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    bundle = tmp_path / "bundle"
    (bundle / "nested" / "empty").mkdir(parents=True)
    tree_id = source.put_tree(bundle)
    work = source.start_work("run")
    (work / "receipt.txt").write_text("receipt")
    source.seal(
        "run",
        {"bundles": [{"path": "wrong", "staged_path": "bundle", "asset_id": tree_id}]},
        work,
    )
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run")

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    restored = Remote(remote_root).restore(target, "run")

    assert (restored / "bundle" / "nested" / "empty").is_dir()
    assert not (restored / "wrong").exists()
    assert target.projection("run")["holds"] == set()


def test_archiving_only_child_publishes_parent_controls_for_fresh_restore(
    tmp_path: Path,
) -> None:
    """A child payload can restore without claiming its parent's payload exists."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    parent_work = source.start_work("parent")
    (parent_work / "parent.txt").write_text("parent payload")
    source.seal("parent", {}, parent_work)
    child_work = source.start_work("child")
    source.register_parent("child", "parent")
    (child_work / "child.txt").write_text("child payload")
    source.seal("child", {}, child_work)
    remote_root = tmp_path / "remote"

    Remote(remote_root).archive(source, "child")

    assert (remote_root / "records" / "parent" / "complete.json").is_file()
    assert not (remote_root / "records" / "parent" / "commit.json").exists()
    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    restored = Remote(remote_root).restore(target, "child")

    assert target.read_record("child")["parents"] == ["parent"]
    assert (restored / "child.txt").read_text() == "child payload"
    assert not list((target.root / "runs" / "parent").rglob("*"))


def test_metadata_sync_publishes_marker_last_payload_free_checkpoint(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    store = Store(tmp_path / "local", machine_id="a")
    store.ensure_initialized("collection")
    work = store.start_work("run")
    (work / "result.txt").write_text("result")
    store.seal("run", {}, work)
    store.label("run", "reviewed")
    remote = tmp_path / "remote"

    Remote(remote).sync_metadata(store.root)

    checkpoint = next((remote / "metadata" / "checkpoints").glob("*.json"))
    value = json.loads(checkpoint.read_text())
    assert value["collection_id"] == "collection"
    assert value["records"]["run"]["root_digest"].startswith("sha256:")
    assert value["events"]
    assert not (remote / "records" / "run" / "commit.json").exists()


def test_checkpoint_imports_two_machine_lineage_and_events_without_payload_claim(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    parent_work = source.start_work("parent")
    (parent_work / "parent.txt").write_text("parent")
    source.seal("parent", {}, parent_work)
    child_work = source.start_work("child")
    source.register_parent("child", "parent")
    (child_work / "child.txt").write_text("child")
    source.seal("child", {}, child_work)
    source.label("child", "reviewed")
    source.hold("parent", "analysis:comparison")
    remote = Remote(tmp_path / "remote")
    remote.sync_metadata(source.root)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    merged = remote.import_metadata(target)

    assert merged["records"] == 2
    assert target.read_record("child")["parents"] == ["parent"]
    assert target.projection("child")["labels"] == {"reviewed"}
    assert target.projection("parent")["holds"] == {"analysis:comparison"}
    assert not (tmp_path / "remote" / "records" / "child" / "commit.json").exists()
    assert not list((tmp_path / "target" / "objects" / "sha256").glob("*/*"))


def test_checkpointed_note_history_imports_exact_append_only_versions(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    source.append_event("note", "run", {"value": "# First discussion\n"})
    source.append_event("note", "run", {"value": "# Revised discussion\n"})
    remote = Remote(tmp_path / "remote")
    remote.sync_metadata(source.root)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    merged = remote.import_metadata(target)

    assert merged["events"] == 3
    assert [item["value"] for item in target.projection("run")["notes"]] == [
        "# First discussion\n",
        "# Revised discussion\n",
    ]


def test_metadata_import_rejects_checkpointed_note_with_changed_bytes(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    event = source.append_event("note", "run", {"value": "trusted note"})
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    remote_note = (
        remote_root / "metadata" / "events" / "machine-a" / f"{event['event_id']}.json"
    )
    remote_note.write_text(json.dumps({"value": "changed note"}))

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    with pytest.raises(IntegrityError, match=r"event.*checkpoint"):
        Remote(remote_root).import_metadata(target)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (None, []),
        ("format", True),
        ("records", []),
        ("records", {"run": []}),
    ],
)
def test_metadata_import_rejects_malformed_checkpoint_records_before_install(
    tmp_path: Path, field: str | None, value: Any
) -> None:
    """Checkpoint shape is validated before any control or event import."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    checkpoint_path = next((remote_root / "metadata" / "checkpoints").glob("*.json"))
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint_path.unlink()
    if field is None:
        checkpoint = value
    else:
        checkpoint[field] = value
    checkpoint_bytes = canonical_json(checkpoint)
    (
        remote_root
        / "metadata"
        / "checkpoints"
        / f"{hashlib.sha256(checkpoint_bytes).hexdigest()}.json"
    ).write_bytes(checkpoint_bytes)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="metadata checkpoint"):
        Remote(remote_root).import_metadata(target)
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


@pytest.mark.parametrize("commit_bytes", [b"{", b"[]", b"null", b"true"])
def test_restore_rejects_malformed_commit_before_local_side_effects(
    tmp_path: Path, commit_bytes: bytes
) -> None:
    """A malformed marker cannot start an import, hold, or payload download."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run")
    (remote_root / "records" / "run" / "commit.json").write_bytes(commit_bytes)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="remote commit marker"):
        Remote(remote_root).restore(target, "run")
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))
    assert not list((target.root / "objects" / "sha256").glob("*/*"))
    assert not list((target.root / "runs" / "run").rglob("*"))


@pytest.mark.parametrize("collection_bytes", [b"null", b"true", b"\xff"])
def test_metadata_import_rejects_present_nonobject_collection(
    tmp_path: Path, collection_bytes: bytes
) -> None:
    """Only a missing collection marker is optional; JSON null is invalid."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    (remote_root / "metadata" / "collection.json").write_bytes(collection_bytes)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="metadata"):
        Remote(remote_root).import_metadata(target)
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


def test_restore_rejects_structurally_invalid_commit_closure_before_import(
    tmp_path: Path,
) -> None:
    """A commit closure is validated before its marker can gate metadata import."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run")
    commit_path = remote_root / "records" / "run" / "commit.json"
    commit = json.loads(commit_path.read_text())
    commit["closure"] = [True]
    commit_path.write_text(json.dumps(commit))

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="object closure"):
        Remote(remote_root).restore(target, "run")
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))
    assert not list((target.root / "objects" / "sha256").glob("*/*"))
    assert not list((target.root / "runs" / "run").rglob("*"))


def test_metadata_import_rejects_nonlist_record_parents_before_install(
    tmp_path: Path,
) -> None:
    """Lineage traversal starts only after parent control shape is validated."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    record_path = remote_root / "records" / "run" / "record.json"
    record = json.loads(record_path.read_text())
    record["parents"] = "parent"
    record_path.write_bytes(canonical_json(record))

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="remote record metadata"):
        Remote(remote_root).import_metadata(target)
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


@pytest.mark.parametrize("name", ["record.json", "manifest.json", "complete.json"])
def test_metadata_import_rejects_nonobject_record_control_before_install(
    tmp_path: Path, name: str
) -> None:
    """Every receipt control document must decode to a JSON object."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    (remote_root / "records" / "run" / name).write_bytes(b"[]")

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="remote record metadata"):
        Remote(remote_root).import_metadata(target)
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


def test_metadata_import_rejects_checkpointed_event_at_a_second_name(
    tmp_path: Path,
) -> None:
    """A checkpoint must not replay one immutable event under a new path."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    event = source.append_event("note", "run", {"value": "one discussion"})
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    original = (
        remote_root / "metadata" / "events" / "machine-a" / f"{event['event_id']}.json"
    )
    duplicate = original.with_name("same-event-under-another-name.json")
    shutil.copy2(original, duplicate)
    checkpoint_path = next((remote_root / "metadata" / "checkpoints").glob("*.json"))
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["events"][duplicate.relative_to(remote_root).as_posix()] = (
        f"sha256:{hashlib.sha256(duplicate.read_bytes()).hexdigest()}"
    )
    checkpoint_bytes = canonical_json(checkpoint)
    (
        remote_root
        / "metadata"
        / "checkpoints"
        / f"{hashlib.sha256(checkpoint_bytes).hexdigest()}.json"
    ).write_bytes(checkpoint_bytes)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="remote event is invalid"):
        Remote(remote_root).import_metadata(target)
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", True),
        ("clock", True),
        ("value", []),
        ("subject", "../outside"),
        ("kind", "unknown-kind"),
        ("kind", []),
        (None, []),
    ],
)
def test_metadata_import_rejects_malformed_checkpointed_event_before_install(
    tmp_path: Path, field: str | None, value: Any
) -> None:
    """Checkpoint hashes bind bytes; they do not make malformed events valid."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    event = source.append_event("note", "run", {"value": "trusted note"})
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    event_path = (
        remote_root / "metadata" / "events" / "machine-a" / f"{event['event_id']}.json"
    )
    malformed = json.loads(event_path.read_text())
    if field is None:
        malformed = value
    else:
        malformed[field] = value
    event_path.write_bytes(canonical_json(malformed))
    checkpoint_path = next((remote_root / "metadata" / "checkpoints").glob("*.json"))
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint_path.unlink()
    checkpoint["events"][event_path.relative_to(remote_root).as_posix()] = (
        f"sha256:{hashlib.sha256(event_path.read_bytes()).hexdigest()}"
    )
    checkpoint_bytes = canonical_json(checkpoint)
    (
        remote_root
        / "metadata"
        / "checkpoints"
        / f"{hashlib.sha256(checkpoint_bytes).hexdigest()}.json"
    ).write_bytes(checkpoint_bytes)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="remote event is invalid"):
        Remote(remote_root).import_metadata(target)
    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


def test_metadata_import_ignores_uncheckpointed_valid_note_during_publication(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)
    remote.sync_metadata(source.root)
    event = source.append_event("note", "run", {"value": "not checkpointed yet"})
    pending = (
        source.root / "metadata" / "events" / "machine-a" / f"{event['event_id']}.json"
    )
    remote_pending = remote_root / "metadata" / "events" / "machine-a" / pending.name
    remote_pending.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pending, remote_pending)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    merged = remote.import_metadata(target)

    assert merged == {"records": 1, "events": 1}
    assert target.projection("run")["notes"] == []
    assert not (
        target.root / "metadata" / "events" / "machine-a" / pending.name
    ).exists()


def test_selected_metadata_import_uses_checkpoint_and_imports_ancestors(
    tmp_path: Path,
) -> None:
    """A selected metadata-only child remains verifiable and usable alone."""
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    parent_work = source.start_work("parent")
    (parent_work / "parent.txt").write_text("parent")
    source.seal("parent", {}, parent_work)
    child_work = source.start_work("child")
    source.register_parent("child", "parent")
    (child_work / "child.txt").write_text("child")
    source.seal("child", {}, child_work)
    remote = Remote(tmp_path / "remote")
    remote.sync_metadata(source.root)

    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    merged = remote.import_metadata(target, "child")

    assert merged["records"] == 2
    assert target.read_record("child")["parents"] == ["parent"]
    assert not list((target.root / "objects" / "sha256").glob("*/*"))


def test_checkpoint_and_event_tampering_fail_closed(tmp_path: Path) -> None:
    from liblaf.cherries.records import Store

    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    work = source.start_work("run")
    (work / "result.txt").write_text("result")
    source.seal("run", {}, work)
    remote_root = tmp_path / "remote"
    Remote(remote_root).sync_metadata(source.root)
    checkpoint = next((remote_root / "metadata" / "checkpoints").glob("*.json"))
    checkpoint.write_bytes(checkpoint.read_bytes() + b" ")
    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")
    with pytest.raises(Exception, match="checkpoint"):
        Remote(remote_root).import_metadata(target)

    clean_remote = tmp_path / "remote-events"
    Remote(clean_remote).sync_metadata(source.root)
    bad = clean_remote / "metadata" / "events" / "machine-a" / "bad.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('{"machine_id":"other"}')
    # A copied but uncheckpointed event is normal marker-last publication
    # state.  It is ignored until a later checkpoint binds its exact bytes.
    assert Remote(clean_remote).import_metadata(target) == {"records": 1, "events": 1}
    assert not (target.root / "metadata" / "events" / "machine-a" / "bad.json").exists()

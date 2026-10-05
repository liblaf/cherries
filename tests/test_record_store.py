# Copyright (c) 2026 liblaf
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries.records import (
    DeletionBlockedError,
    IntegrityError,
    Store,
    canonical_json,
)


def seal(
    store: Store, run_id: str, text: str, *, parents: list[str] | None = None
) -> dict[str, Any]:
    work = store.start_work(run_id)
    (work / "outputs").mkdir()
    (work / "outputs" / "result.txt").write_text(text)
    return store.seal(
        run_id, {"parents": parents or [], "command": ["python", "run.py"]}, work
    )


def test_seal_deduplicates_and_materializes_independent_copy(tmp_path: Path) -> None:
    store = Store(tmp_path / "store", machine_id="machine-a")
    first = seal(store, "one", "same bytes")
    second = seal(store, "two", "same bytes")

    assert first["assets"] == second["assets"]
    assert len(list((store.root / "objects" / "sha256").glob("*/*"))) == 1
    binding = store.resolve_asset(first["assets"][0]["asset_id"])
    assert binding["run_id"] == "one"
    output = store.materialize("one", "outputs/result.txt")
    assert (
        output.stat().st_ino
        != store.object_path(first["assets"][0]["asset_id"]).stat().st_ino
    )
    output.write_text("changed view")
    assert store.materialize("two", "outputs/result.txt").read_text() == "same bytes"


def test_parent_blocks_discard_and_pending_blocks_prune(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "parent", "input")
    child_work = store.start_work("child")
    store.register_parent("child", "parent")
    (child_work / "outputs").mkdir()
    (child_work / "outputs" / "result.txt").write_text("output")
    store.seal("child", {}, child_work)

    receipt = store.pause_maintenance()
    plan = store.plan_discard("parent", inventory_complete=True, maintenance=True)
    assert plan["allowed"] is False
    assert plan["blocked"] == ["child"]
    store.resume_maintenance(receipt["token"])
    store.start_work("pending")
    assert (
        store.plan_prune(inventory_complete=True, maintenance=True)["allowed"] is False
    )


def test_important_hold_and_failure_cleanup_are_safe(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "saved", "value")
    store.mark("saved", important=True)
    store.hold("saved", "meeting")
    receipt = store.pause_maintenance()
    assert (
        store.plan_discard("saved", inventory_complete=True, maintenance=True)[
            "allowed"
        ]
        is False
    )
    store.resume_maintenance(receipt["token"])

    work = store.start_work("failed")
    (work / "log.txt").write_text("trace")
    event = store.cancel_failed_work("failed", {"exit_code": 1})
    assert event["kind"] == "execution-failed"
    assert not work.exists()
    assert (store.root / "metadata" / "events" / store.machine_id).is_dir()


def test_tree_is_deterministic_and_legacy_is_explicitly_incomplete(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store")
    source = tmp_path / "legacy"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "x.txt").write_text("x")
    tree = store.put_tree(source)
    restored = store.materialize_tree(tree, tmp_path / "restored")
    assert (restored / "nested" / "x.txt").read_text() == "x"
    copied = Store(tmp_path / "copy")
    copied.ensure_initialized()
    copied.import_tree_object(store.tree_object_path(tree), tree)
    assert (
        copied.tree_object_path(tree).read_bytes()
        == store.tree_object_path(tree).read_bytes()
    )
    imported = store.import_legacy(source, "old-local")
    assert (
        store.read_record(imported["run_id"])["record"]["legacy"]["provenance"]
        == "incomplete"
    )


def test_conflicting_collection_and_self_parent_are_rejected(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    store.ensure_initialized("collection-a")
    with pytest.raises(IntegrityError):
        store.ensure_initialized("collection-b")
    store.start_work("run")
    with pytest.raises(IntegrityError):
        store.register_parent("run", "run")
    with pytest.raises(DeletionBlockedError):
        store.apply_prune()


def test_machine_identity_persists_across_store_instances(tmp_path: Path) -> None:
    root = tmp_path / "store"
    first = Store(root)
    machine = first.machine_id
    assert Store(root).machine_id == machine
    with pytest.raises(IntegrityError):
        Store(root, machine_id="other-machine").ensure_initialized()


def test_leaf_retirement_releases_its_object_root(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    sealed = seal(store, "leaf", "unique")
    asset_id = sealed["assets"][0]["asset_id"]
    receipt = store.pause_maintenance()
    assert store.apply_discard("leaf", inventory_complete=True, maintenance=True)[
        "allowed"
    ]
    assert store.is_retired("leaf")
    store.resume_maintenance(receipt["token"])
    receipt = store.pause_maintenance()
    plan = store.plan_prune(inventory_complete=True, maintenance=True)
    assert plan["allowed"]
    store.apply_prune(inventory_complete=True, maintenance=True)
    digest = asset_id.removeprefix("sha256:")
    assert not (store.root / "objects" / "sha256" / digest[:2] / digest).exists()
    store.resume_maintenance(receipt["token"])


def test_failed_attempt_is_browseable_without_a_sealed_record(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    work = store.start_work("failed")
    (work / "log.txt").write_text("trace")
    store.cancel_failed_work(
        "failed", {"command": ["python", "x.py"], "tail": "x" * 20_000}
    )
    attempt = store.list_attempts()[0]
    assert attempt["status"] == "execution-failed"
    assert attempt["diagnostics"]["truncated"] is True
    assert store.list_records() == []


def test_observed_remove_preserves_unseen_remote_label(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "run", "value")
    local = store.label("run", "good")
    remote = {
        "format": 1,
        "event_id": "remote-add",
        "machine_id": "machine-b",
        "clock": 1,
        "kind": "label",
        "subject": "run",
        "value": {"label": "good", "operation_id": "remote-op"},
    }
    store.label("run", "good", present=False)
    store.import_metadata_file(
        Path("metadata/events/machine-b/remote-add.json"),
        json.dumps(remote, sort_keys=True, separators=(",", ":")).encode(),
    )
    assert store.projection("run")["labels"] == {"good"}
    assert local["value"]["operation_id"] != "remote-op"


def test_foreign_event_blocks_local_maintenance(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "run", "value")
    event = {
        "format": 1,
        "event_id": "foreign",
        "machine_id": "machine-b",
        "clock": 1,
        "kind": "review",
        "subject": "run",
        "value": {"status": "good"},
    }
    store.import_metadata_file(
        Path("metadata/events/machine-b/foreign.json"),
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode(),
    )
    with pytest.raises(DeletionBlockedError):
        store.pause_maintenance()


def test_local_event_clock_advances_past_observed_remote_clock(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "run", "value")
    remote = {
        "format": 1,
        "event_id": "remote",
        "machine_id": "machine-b",
        "clock": 41,
        "kind": "review",
        "subject": "run",
        "value": {"status": "good"},
    }
    store.import_metadata_file(
        Path("metadata/events/machine-b/remote.json"),
        json.dumps(remote, sort_keys=True, separators=(",", ":")).encode(),
    )
    assert store.review("run", "local")["clock"] == 42


def test_manifest_tampering_is_detected_after_a_cached_read(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "run", "value")
    manifest_path = store.root / "records" / "run" / "manifest.json"
    store.read_manifest("run")
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "outputs/tampered.txt"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(IntegrityError):
        store.read_manifest("run")


def test_corrupt_payload_is_never_materialized(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    saved = seal(store, "run", "correct")
    store.object_path(saved["assets"][0]["asset_id"]).write_text("corrupt")
    destination = tmp_path / "restored.txt"
    with pytest.raises(IntegrityError, match="CAS object bytes"):
        store.materialize("run", "outputs/result.txt", destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".materialize.*"))


def test_tree_preserves_empty_directories_and_rejects_unsafe_paths(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store")
    source = tmp_path / "source"
    (source / "empty" / "nested").mkdir(parents=True)
    tree_id = store.put_tree(source)
    destination = store.materialize_tree(tree_id, tmp_path / "copy")
    assert (destination / "empty" / "nested").is_dir()
    descriptor = {
        "format": 1,
        "kind": "cherries-tree",
        "entries": [],
        "directories": ["../escape"],
    }
    data = canonical_json(descriptor)
    bad_id = "sha256-tree:" + hashlib.sha256(b"cherries-tree-v1\0" + data).hexdigest()
    downloaded = tmp_path / "downloaded.json"
    downloaded.write_bytes(data)
    with pytest.raises(IntegrityError, match="relative and contained"):
        store.import_tree_object(downloaded, bad_id)
    store.tree_object_path(tree_id).write_bytes(data)
    with pytest.raises(IntegrityError, match="tree object is corrupt"):
        store.materialize_tree(tree_id, tmp_path / "tampered")


def test_retired_child_still_blocks_parent_discard(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "parent", "input")
    seal(store, "child", "output", parents=["parent"])
    receipt = store.pause_maintenance()
    store.apply_discard("child", inventory_complete=True, maintenance=True)
    store.resume_maintenance(receipt["token"])
    receipt = store.pause_maintenance()
    plan = store.plan_discard("parent", inventory_complete=True, maintenance=True)
    assert plan["blocked"] == ["child"]
    store.resume_maintenance(receipt["token"])


def test_repeated_materialization_reads_large_manifest_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "store")
    work = store.start_work("run")
    for number in range(30):
        (work / f"frame-{number}.txt").write_text(str(number))
    store.seal("run", {}, work)
    reader = Store(store.root)
    manifest_reads = []
    original = Path.read_bytes

    def counted(path: Path) -> bytes:
        if path.name == "manifest.json":
            manifest_reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    for number in range(30):
        assert reader.materialize("run", f"frame-{number}.txt").read_text() == str(
            number
        )
    assert len(manifest_reads) == 1
    returned = reader.read_manifest("run")
    returned["files"].clear()
    assert len(reader.read_manifest("run")["files"]) == 30


def test_restored_resident_bundle_protects_shared_tree_members(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "data").write_text("shared tree member")
    tree = store.put_tree(bundle)
    for run_id in ("one", "two"):
        work = store.start_work(run_id)
        store.seal(
            run_id, {"bundles": [{"path": "outputs/tree", "asset_id": tree}]}, work
        )
    member = store.resolve_asset(tree)["tree"]["entries"][0]["asset_id"]
    store.append_event("local-evicted", "two", {})
    store.append_event("location-restored", "two", {})
    assert store.evict_local("one", remote_verified=True)["allowed"]
    assert store.object_path(member).is_file()


def test_reader_can_browse_during_another_process_payload_write(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    seal(store, "saved", "payload")
    locker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read()",
            str(store.root / ".store.lock"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert locker.stdout is not None
        assert locker.stdout.readline().strip() == "locked"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from pathlib import Path; from liblaf.cherries.records import Store; s=Store(Path(sys.argv[1])); assert s.list_records()==['saved']; assert s.read_record('saved')['run_id']=='saved'; assert s.machine_id",
                str(store.root),
            ],
            check=True,
            capture_output=True,
            timeout=5,
        )
        assert result.returncode == 0
    finally:
        locker.communicate(input="", timeout=5)

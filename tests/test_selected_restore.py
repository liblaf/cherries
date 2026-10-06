# Copyright (c) 2026 liblaf
"""Selected remote import and restore retain only the selected lineage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from liblaf.cherries._remote import IntegrityError, Remote
from liblaf.cherries.records import Store, canonical_json


def _seal(
    store: Store,
    run_id: str,
    files: dict[str, str],
    record: dict[str, object] | None = None,
) -> None:
    work = store.start_work(run_id)
    for relative, contents in files.items():
        path = work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    store.seal(run_id, record or {}, work)


def _asset_id(store: Store, run_id: str, path: str) -> str:
    return next(
        item["asset_id"]
        for item in store.read_manifest(run_id)["files"]
        if item["path"] == path
    )


def _event_subjects(store: Store) -> set[str]:
    return {
        json.loads(path.read_text())["subject"]
        for path in (store.root / "metadata" / "events").glob("*/*.json")
    }


def _source_with_selected_child(tmp_path: Path) -> tuple[Store, Remote]:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    _seal(source, "A", {"outputs/input.txt": "parent input\n"})
    parent_asset = _asset_id(source, "A", "outputs/input.txt")
    _seal(
        source,
        "B",
        {
            "inputs/parent.txt": "parent input\n",
            "outputs/child.txt": "child output\n",
        },
        {
            "parents": ["A"],
            "input_bindings": [
                {
                    "asset_id": parent_asset,
                    "manifest_digest": source.read_record("A")["manifest_digest"],
                    "staged_path": "inputs/parent.txt",
                }
            ],
        },
    )
    _seal(source, "C", {"outputs/unrelated.txt": "unrelated\n"})
    for run_id in ("A", "B", "C"):
        source.label(run_id, f"label-{run_id}")
    remote = Remote(tmp_path / "remote")
    remote.archive(source, "B")
    return source, remote


def test_selected_metadata_import_installs_only_selected_lineage_events(
    tmp_path: Path,
) -> None:
    _source, remote = _source_with_selected_child(tmp_path)
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")

    merged = remote.import_metadata(target, "B")

    assert merged["records"] == 2
    assert target.list_records() == ["A", "B"]
    assert _event_subjects(target) == {"A", "B"}
    assert not (target.root / "records" / "C").exists()


def test_selected_restore_materializes_only_requested_lineage(
    tmp_path: Path,
) -> None:
    _source, remote = _source_with_selected_child(tmp_path)
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")

    restored = remote.restore(target, "B")

    assert restored == target.root / "runs" / "B"
    assert target.list_records() == ["A", "B"]
    assert _event_subjects(target) == {"A", "B"}
    assert (restored / "inputs" / "parent.txt").read_text() == "parent input\n"
    assert (restored / "outputs" / "child.txt").read_text() == "child output\n"
    assert not (target.root / "records" / "C").exists()
    assert not (target.root / "runs" / "C").exists()


def test_selected_import_keeps_new_events_for_existing_local_ancestors(
    tmp_path: Path,
) -> None:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    _seal(source, "G", {"outputs/grandparent.txt": "grandparent\n"})
    _seal(
        source,
        "A",
        {"outputs/input.txt": "parent input\n"},
        {"parents": ["G"]},
    )
    remote = Remote(tmp_path / "remote")
    remote.sync_metadata(source.root)
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")
    remote.import_metadata(target)

    parent_asset = _asset_id(source, "A", "outputs/input.txt")
    _seal(
        source,
        "B",
        {"inputs/parent.txt": "parent input\n", "outputs/child.txt": "child\n"},
        {
            "parents": ["A"],
            "input_bindings": [
                {
                    "asset_id": parent_asset,
                    "staged_path": "inputs/parent.txt",
                }
            ],
        },
    )
    _seal(source, "C", {"outputs/unrelated.txt": "unrelated\n"})
    source.append_event("note", "G", {"value": "new grandparent history"})
    source.append_event("note", "A", {"value": "new parent history"})
    source.label("B", "selected")
    source.label("C", "unrelated")
    remote.sync_metadata(source.root)

    merged = remote.import_metadata(target, "B")

    assert merged["records"] == 1
    assert target.list_records() == ["A", "B", "G"]
    assert _event_subjects(target) == {"A", "B", "G"}
    assert [item["value"] for item in target.projection("G")["notes"]] == [
        "new grandparent history"
    ]
    assert [item["value"] for item in target.projection("A")["notes"]] == [
        "new parent history"
    ]


def test_global_metadata_import_keeps_unrelated_records_and_events(
    tmp_path: Path,
) -> None:
    _source, remote = _source_with_selected_child(tmp_path)
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")

    remote.import_metadata(target)

    assert target.list_records() == ["A", "B", "C"]
    assert _event_subjects(target) == {"A", "B", "C"}


def test_selected_import_rejects_invalid_unrelated_checkpoint_event_before_writes(
    tmp_path: Path,
) -> None:
    _source, remote = _source_with_selected_child(tmp_path)
    remote_root = Path(remote.remote)
    event_path = next(
        path
        for path in (remote_root / "metadata" / "events").glob("*/*.json")
        if json.loads(path.read_text())["subject"] == "C"
    )
    malformed = json.loads(event_path.read_text())
    malformed["value"] = []
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
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="remote event is invalid"):
        remote.import_metadata(target, "B")

    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))

# Copyright (c) 2026 liblaf
"""Regression tests for Store recovery and remote control integrity."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from liblaf.cherries.records import IntegrityError, Store, canonical_json


def _seal(store: Store, run_id: str) -> None:
    work = store.start_work(run_id)
    (work / "result.txt").write_text("result")
    store.seal(run_id, {}, work)


def test_start_work_recovers_only_a_missing_pending_intent(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    work = store.start_work("run", {"pid": 1234, "purpose": "test"})
    pending = store.root / "pending" / "run.json"
    pending.unlink()

    assert store.start_work("run") == work
    assert json.loads(pending.read_text()) == {
        "metadata": {"pid": 1234, "purpose": "test"},
        "roots": [],
        "run_id": "run",
    }


def test_start_work_never_overwrites_an_orphan_pending_intent(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    store.ensure_initialized()
    pending = store.root / "pending" / "run.json"
    pending.write_bytes(
        canonical_json(
            {"run_id": "run", "roots": ["sha256:" + "a" * 64], "metadata": {}}
        )
    )
    original = pending.read_bytes()

    with pytest.raises(IntegrityError, match="pending intent exists"):
        store.start_work("run")

    assert pending.read_bytes() == original
    assert not (store.root / "work" / "run").exists()


def test_initialization_recovers_owned_work_after_seal_publication(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store")
    _seal(store, "run")
    work = store.root / "work" / "run"
    work.mkdir(parents=True)
    (work / ".cherries-work.json").write_bytes(
        canonical_json({"run_id": "run", "metadata": {}})
    )
    pending = store.root / "pending" / "run.json"
    pending.write_bytes(canonical_json({"run_id": "run", "roots": [], "metadata": {}}))

    Store(store.root).ensure_initialized()

    assert not work.exists()
    assert not pending.exists()
    assert Store(store.root).read_record("run")["run_id"] == "run"


def test_initialization_preserves_work_when_sealed_payload_is_corrupt(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store")
    _seal(store, "run")
    work = store.root / "work" / "run"
    work.mkdir(parents=True)
    (work / ".cherries-work.json").write_bytes(
        canonical_json({"run_id": "run", "metadata": {}})
    )
    pending = store.root / "pending" / "run.json"
    pending.write_bytes(canonical_json({"run_id": "run", "roots": [], "metadata": {}}))
    (store.root / "records" / "run" / "manifest.json").write_text("{}")

    Store(store.root).ensure_initialized()

    assert work.is_dir()
    assert pending.is_file()


def test_initialization_preserves_work_owned_by_a_live_process(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    _seal(store, "run")
    work = store.root / "work" / "run"
    work.mkdir(parents=True)
    (work / ".cherries-work.json").write_bytes(
        canonical_json({"run_id": "run", "metadata": {"pid": os.getpid()}})
    )
    pending = store.root / "pending" / "run.json"
    pending.write_bytes(
        canonical_json({"run_id": "run", "roots": [], "metadata": {"pid": os.getpid()}})
    )

    Store(store.root).ensure_initialized()

    assert work.is_dir()
    assert pending.is_file()


@pytest.mark.parametrize(
    ("relative", "event"),
    [
        (
            Path("metadata/events/machine-a/event.json"),
            {"format": True},
        ),
        (
            Path("metadata/events/machine-a/event.json"),
            {"clock": True},
        ),
        (
            Path("metadata/events/machine-a/event.json"),
            {"clock": -1},
        ),
        (
            Path("metadata/events/machine-a/event.json"),
            {"value": []},
        ),
        (
            Path("metadata/events/machine-a/event.json"),
            {"subject": "../run"},
        ),
        (
            Path("metadata/events/machine-a/event.json"),
            {"event_id": "other"},
        ),
    ],
)
def test_import_metadata_event_rejects_poisoned_control_fields(
    tmp_path: Path, relative: Path, event: dict[str, object]
) -> None:
    store = Store(tmp_path / "store")
    value = {
        "format": 1,
        "event_id": "event",
        "machine_id": "machine-a",
        "clock": 1,
        "kind": "label",
        "subject": "run",
        "value": {"label": "good", "operation_id": "operation"},
    }
    value.update(event)

    with pytest.raises(IntegrityError):
        store.import_metadata_file(relative, canonical_json(value))

    assert not (store.root / relative).exists()


def test_remote_record_must_bind_manifest_and_machine_identity(tmp_path: Path) -> None:
    source = Store(tmp_path / "source", machine_id="machine-a")
    source.ensure_initialized("collection")
    _seal(source, "run")
    source_dir = source.root / "records" / "run"
    record = json.loads((source_dir / "record.json").read_text())
    manifest = json.loads((source_dir / "manifest.json").read_text())

    record["manifest_digest"] = "sha256:" + "0" * 64
    record_digest = hashlib.sha256(canonical_json(record)).hexdigest()
    manifest_digest = hashlib.sha256(canonical_json(manifest)).hexdigest()
    complete = {
        "run_id": "run",
        "record_digest": f"sha256:{record_digest}",
        "manifest_digest": f"sha256:{manifest_digest}",
        "root_digest": "sha256:"
        + hashlib.sha256(
            canonical_json({"record": record_digest, "manifest": manifest_digest})
        ).hexdigest(),
    }
    target = Store(tmp_path / "target", machine_id="machine-b")
    target.ensure_initialized("collection")

    with pytest.raises(IntegrityError, match="does not bind its manifest"):
        target.import_remote_record(record, manifest, complete)

    record["manifest_digest"] = f"sha256:{manifest_digest}"
    record.pop("machine_id")
    record_digest = hashlib.sha256(canonical_json(record)).hexdigest()
    complete["record_digest"] = f"sha256:{record_digest}"
    complete["root_digest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json({"record": record_digest, "manifest": manifest_digest})
        ).hexdigest()
    )
    with pytest.raises(IntegrityError, match="machine identity"):
        target.import_remote_record(record, manifest, complete)

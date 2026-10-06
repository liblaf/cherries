# Copyright (c) 2026 liblaf
"""Archive publication outcomes preserve remote facts when local annotation fails."""

from __future__ import annotations

import errno
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries import _cli
from liblaf.cherries.records import Store


def _seal(store: Store, run_id: str, contents: str) -> str:
    work = store.start_work(run_id)
    output = work / "outputs" / "result.txt"
    output.parent.mkdir()
    output.write_text(contents)
    store.seal(run_id, {}, work)
    store.materialize(run_id, "outputs/result.txt")
    return next(item["asset_id"] for item in store.read_manifest(run_id)["files"])


def _event_kinds(store: Store) -> set[str]:
    return {
        json.loads(path.read_text())["kind"]
        for path in (store.root / "metadata" / "events").glob("*/*.json")
    }


def _archive_json(
    capsys: pytest.CaptureFixture[str], store: Store, remote: Path, *run_ids: str
) -> dict[str, Any]:
    capsys.readouterr()
    assert (
        _cli.main(
            [
                "--storage",
                str(store.root),
                "--machine-id",
                store.machine_id,
                "--json",
                "archive",
                *run_ids,
                "--remote",
                str(remote),
                "--evict",
            ]
        )
        == 0
    )
    return json.loads(capsys.readouterr().out)


def test_archive_reports_committed_location_when_local_annotation_hits_enospc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = Store(tmp_path / "store", machine_id="machine")
    store.ensure_initialized("collection")
    asset_id = _seal(store, "run", "payload\n")
    remote = tmp_path / "remote"
    machine_path = store.root / "machine.json"
    original_atomic_json = store._atomic_json  # noqa: SLF001

    def enospc_after_commit(path: Path, value: dict[str, Any]) -> None:
        if (
            path == machine_path
            and (remote / "records" / "run" / "commit.json").is_file()
        ):
            raise OSError(errno.ENOSPC, "No space left on device")
        original_atomic_json(path, value)

    monkeypatch.setattr(store, "_atomic_json", enospc_after_commit)
    monkeypatch.setattr(_cli, "_store", lambda *_args: store)

    outcome = _archive_json(capsys, store, remote, "run")

    commit_path = remote / "records" / "run" / "commit.json"
    assert commit_path.is_file()
    commit = hashlib.sha256(commit_path.read_bytes()).hexdigest()
    assert outcome["locations"] == [
        {"remote": str(remote), "run_id": "run", "commit": commit}
    ]
    assert outcome["warnings"] == [
        {
            "stage": "local_annotation",
            "run_id": "run",
            "remote": str(remote),
            "commit": commit,
            "errno": errno.ENOSPC,
            "error": "[Errno 28] No space left on device",
        }
    ]
    assert outcome["eviction_skipped"] == [
        {"run_id": "run", "reason": "local_annotation_failed"}
    ]
    assert (store.root / "runs" / "run" / "outputs" / "result.txt").read_text() == (
        "payload\n"
    )
    assert store.object_path(asset_id).is_file()
    assert "location-verified" not in _event_kinds(store)
    assert "local-evicted" not in _event_kinds(store)


def test_archive_keeps_every_committed_batch_location_when_annotations_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = Store(tmp_path / "store", machine_id="machine")
    store.ensure_initialized("collection")
    assets = {run_id: _seal(store, run_id, f"{run_id}\n") for run_id in ("one", "two")}
    remote = tmp_path / "remote"
    machine_path = store.root / "machine.json"
    original_atomic_json = store._atomic_json  # noqa: SLF001

    def enospc_after_each_commit(path: Path, value: dict[str, Any]) -> None:
        if path == machine_path and any(
            (remote / "records" / run_id / "commit.json").is_file()
            for run_id in ("one", "two")
        ):
            raise OSError(errno.ENOSPC, "No space left on device")
        original_atomic_json(path, value)

    monkeypatch.setattr(store, "_atomic_json", enospc_after_each_commit)
    monkeypatch.setattr(_cli, "_store", lambda *_args: store)

    outcome = _archive_json(capsys, store, remote, "one", "two")

    assert [location["run_id"] for location in outcome["locations"]] == ["one", "two"]
    assert [warning["run_id"] for warning in outcome["warnings"]] == ["one", "two"]
    assert outcome["eviction_skipped"] == [
        {"run_id": "one", "reason": "local_annotation_failed"},
        {"run_id": "two", "reason": "local_annotation_failed"},
    ]
    for run_id, asset_id in assets.items():
        assert (remote / "records" / run_id / "commit.json").is_file()
        assert (
            store.root / "runs" / run_id / "outputs" / "result.txt"
        ).read_text() == (f"{run_id}\n")
        assert store.object_path(asset_id).is_file()


def test_archive_evicts_later_records_after_an_earlier_annotation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = Store(tmp_path / "store", machine_id="machine")
    store.ensure_initialized("collection")
    first_asset = _seal(store, "one", "one\n")
    second_asset = _seal(store, "two", "two\n")
    remote = tmp_path / "remote"
    machine_path = store.root / "machine.json"
    original_atomic_json = store._atomic_json  # noqa: SLF001
    failed = False

    def enospc_once_after_first_commit(path: Path, value: dict[str, Any]) -> None:
        nonlocal failed
        if (
            not failed
            and path == machine_path
            and (remote / "records" / "one" / "commit.json").is_file()
        ):
            failed = True
            raise OSError(errno.ENOSPC, "No space left on device")
        original_atomic_json(path, value)

    monkeypatch.setattr(store, "_atomic_json", enospc_once_after_first_commit)
    monkeypatch.setattr(_cli, "_store", lambda *_args: store)

    outcome = _archive_json(capsys, store, remote, "one", "two")

    assert [location["run_id"] for location in outcome["locations"]] == ["one", "two"]
    assert [warning["run_id"] for warning in outcome["warnings"]] == ["one"]
    assert outcome["eviction_skipped"] == [
        {"run_id": "one", "reason": "local_annotation_failed"}
    ]
    assert [item["run_id"] for item in outcome["evicted"]] == ["two"]
    assert (
        store.root / "runs" / "one" / "outputs" / "result.txt"
    ).read_text() == "one\n"
    assert store.object_path(first_asset).is_file()
    assert not (store.root / "runs" / "two").exists()
    second_digest = second_asset.removeprefix("sha256:")
    assert not (
        store.root / "objects" / "sha256" / second_digest[:2] / second_digest
    ).exists()
    assert "location-verified" in _event_kinds(store)
    assert "local-evicted" in _event_kinds(store)


def test_archive_still_fails_before_commit_when_remote_publication_rejects_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = Store(tmp_path / "store", machine_id="machine")
    store.ensure_initialized("collection")
    asset_id = _seal(store, "run", "payload\n")
    remote = tmp_path / "remote"
    digest = asset_id.removeprefix("sha256:")
    conflicting = remote / "objects" / "sha256" / digest[:2] / digest
    conflicting.parent.mkdir(parents=True)
    conflicting.write_text("different bytes\n")

    with pytest.raises(SystemExit, match="2"):
        _archive_json(capsys, store, remote, "run")

    assert not (remote / "records" / "run" / "commit.json").exists()
    assert (store.root / "runs" / "run" / "outputs" / "result.txt").read_text() == (
        "payload\n"
    )
    assert store.object_path(asset_id).is_file()
    assert "location-verified" not in _event_kinds(store)

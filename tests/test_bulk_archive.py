# Copyright (c) 2026 liblaf
"""Bulk archival shares metadata proofs without weakening per-record commits."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries import _cli
from liblaf.cherries._remote import IntegrityError, Remote, RemoteError
from liblaf.cherries.records import NotFoundError, Store


def _seal(store: Store, run_id: str, *, record: dict[str, Any] | None = None) -> str:
    work = store.start_work(run_id)
    (work / "result.txt").write_text(f"{run_id} payload\n")
    store.seal(run_id, record or {}, work)
    store.materialize(run_id, "result.txt")
    return store.read_manifest(run_id)["files"][0]["asset_id"]


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "source", machine_id="source-machine")
    store.ensure_initialized("collection")
    return store


def _archive(
    store: Store,
    remote: Path,
    capsys: pytest.CaptureFixture[str],
    *run_ids: str,
    evict: bool = False,
) -> dict[str, Any]:
    args = [
        "--storage",
        str(store.root),
        "--machine-id",
        store.machine_id,
        "--json",
        "archive",
        *run_ids,
        "--remote",
        str(remote),
    ]
    if evict:
        args.append("--evict")
    capsys.readouterr()
    assert _cli.main(args) == 0
    return json.loads(capsys.readouterr().out)


def _checkpoints(remote: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text())
        for path in (remote / "metadata" / "checkpoints").glob("*.json")
    ]


def _event_kinds(remote: Path) -> set[str]:
    return {
        json.loads(path.read_text())["kind"]
        for path in (remote / "metadata" / "events").glob("*/*.json")
    }


def test_cli_batch_publishes_collection_controls_once_and_final_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    for run_id in ("one", "two", "unselected"):
        _seal(store, run_id)
    remote = tmp_path / "remote"
    publications: list[Path] = []
    original = Remote._publish  # noqa: SLF001

    def observe(self: Remote, source: Path, relative: Path, digest: str) -> None:
        publications.append(relative)
        original(self, source, relative, digest)

    monkeypatch.setattr(Remote, "_publish", observe)

    result = _archive(store, remote, capsys, "one", "two", "one")

    assert [item["run_id"] for item in result["locations"]] == ["one", "two"]
    counts = Counter(publications)
    for name in ("record.json", "manifest.json", "complete.json"):
        assert counts[Path("records") / "unselected" / name] == 1
        assert counts[Path("records") / "one" / name] <= 2
        assert counts[Path("records") / "two" / name] <= 2
    assert not (remote / "records" / "unselected" / "commit.json").exists()
    checkpoints = _checkpoints(remote)
    assert len(checkpoints) == 2
    assert all(
        set(checkpoint["records"]) == {"one", "two", "unselected"}
        for checkpoint in checkpoints
    )
    assert "location-verified" in _event_kinds(remote)
    target = Store(tmp_path / "reader", machine_id="reader")
    target.ensure_initialized("collection")
    Remote(remote).import_metadata(target)
    locations = [
        json.loads(path.read_text())
        for path in (target.root / "metadata" / "events").glob("*/*.json")
        if json.loads(path.read_text())["kind"] == "location-verified"
    ]
    assert {event["subject"] for event in locations} == {"one", "two"}
    assert all(event["value"]["remote"] == str(remote) for event in locations)


def test_batch_keeps_transitive_closures_and_parent_controls_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    _seal(store, "parent")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "member.txt").write_text("tree member\n")
    tree_id = store.put_tree(tree)
    _seal(
        store,
        "child",
        record={"parents": ["parent"], "bundles": [{"asset_id": tree_id}]},
    )
    assert store.read_record("child")["parents"] == ["parent"]
    _seal(store, "other")
    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)
    original = remote._publish  # noqa: SLF001
    committed: list[str] = []

    def inspect_commit(source: Path, relative: Path, digest: str) -> None:
        if relative.name == "commit.json":
            run_id = relative.parts[1]
            marker = json.loads(source.read_text())
            assert set(marker["closure"]) == set(store.asset_closure(run_id))
            for asset_id in marker["closure"]:
                kind, value = asset_id.split(":", 1)
                assert (remote_root / "objects" / kind / value[:2] / value).is_file()
            for name in ("record.json", "manifest.json", "complete.json"):
                assert (remote_root / "records" / run_id / name).is_file()
                assert (remote_root / "records" / "parent" / name).is_file()
            committed.append(run_id)
        original(source, relative, digest)

    monkeypatch.setattr(remote, "_publish", inspect_commit)
    with remote.archive_batch(store, ["child", "other"]) as batch:
        for run_id in batch.run_ids:
            batch.archive(run_id)
    assert committed == ["child", "other"]
    assert not (remote_root / "records" / "parent" / "commit.json").exists()
    target = Store(tmp_path / "reader", machine_id="reader")
    target.ensure_initialized("collection")
    assert (
        remote.restore(target, "child") / "result.txt"
    ).read_text() == "child payload\n"
    assert (
        target.materialize_tree(tree_id, tmp_path / "tree-read") / "member.txt"
    ).read_text() == "tree member\n"


def test_batch_final_checkpoint_includes_concurrent_records_and_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    _seal(store, "selected")
    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)
    original = remote._publish  # noqa: SLF001
    added = False

    def add_during_commit(source: Path, relative: Path, digest: str) -> None:
        nonlocal added
        original(source, relative, digest)
        if relative == Path("records/selected/commit.json") and not added:
            added = True
            _seal(store, "concurrent")
            store.label("selected", "weekly-meeting")

    monkeypatch.setattr(remote, "_publish", add_during_commit)
    with remote.archive_batch(store, ["selected"]) as batch:
        batch.archive("selected")
    assert added
    assert not (remote_root / "records" / "concurrent" / "commit.json").exists()
    assert any(
        set(checkpoint["records"]) == {"selected", "concurrent"}
        for checkpoint in _checkpoints(remote_root)
    )
    target = Store(tmp_path / "reader", machine_id="reader")
    target.ensure_initialized("collection")
    remote.import_metadata(target)
    assert set(target.list_records()) == {"selected", "concurrent"}
    assert target.projection("selected")["labels"] == {"weekly-meeting"}


def test_batch_selection_is_frozen_and_closed_context_cannot_publish(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seal(store, "one")
    remote_root = tmp_path / "remote"
    with Remote(remote_root).archive_batch(store, ["one", "one"]) as batch:
        assert batch.run_ids == ("one",)
        _seal(store, "late")
        with pytest.raises((RemoteError, ValueError), match=r"select|batch"):
            batch.archive("late")
        batch.archive("one")
    with pytest.raises((RemoteError, ValueError), match=r"closed|batch"):
        batch.archive("one")
    assert not (remote_root / "records" / "late" / "commit.json").exists()


def test_batch_proof_cache_does_not_hide_changed_control_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seal(store, "selected")
    _seal(store, "unselected")
    remote_root = tmp_path / "remote"

    def archive_changed_metadata() -> None:
        with Remote(remote_root).archive_batch(store, ["selected"]) as batch:
            batch.archive("selected")
            control = store.root / "records" / "unselected" / "record.json"
            control.write_text(control.read_text() + "\n")

    with pytest.raises(IntegrityError, match=r"changed|differs|metadata"):
        archive_changed_metadata()
    assert (remote_root / "records" / "selected" / "commit.json").is_file()
    assert len(_checkpoints(remote_root)) == 1


def test_cli_batch_payload_failure_never_evicts_earlier_committed_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    first = _seal(store, "one")
    second = _seal(store, "two")
    remote = tmp_path / "remote"
    digest = second.removeprefix("sha256:")
    bad = remote / "objects" / "sha256" / digest[:2] / digest
    bad.parent.mkdir(parents=True)
    bad.write_text("corrupt remote object")
    with pytest.raises(SystemExit, match="2"):
        _archive(store, remote, capsys, "one", "two", evict=True)
    assert (remote / "records" / "one" / "commit.json").is_file()
    assert not (remote / "records" / "two" / "commit.json").exists()
    assert store.object_path(first).is_file()
    assert (store.root / "runs" / "one" / "result.txt").is_file()
    assert "local-evicted" not in {
        json.loads(path.read_text())["kind"]
        for path in (store.root / "metadata" / "events").glob("*/*.json")
    }


@pytest.mark.parametrize("fail_after_eviction", [False, True])
def test_cli_batch_reports_metadata_failure_without_losing_committed_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    fail_after_eviction: bool,
) -> None:
    store = _store(tmp_path)
    asset_id = _seal(store, "one")
    remote = tmp_path / "remote"
    original = Remote._publish  # noqa: SLF001

    def reject_delta(self: Remote, source: Path, relative: Path, digest: str) -> None:
        if relative.parts[:2] == ("metadata", "events"):
            kind = json.loads(source.read_text())["kind"]
            if kind == (
                "local-evicted" if fail_after_eviction else "location-verified"
            ):
                message = "remote metadata unavailable"
                raise OSError(message)
        original(self, source, relative, digest)

    monkeypatch.setattr(Remote, "_publish", reject_delta)
    result = _archive(store, remote, capsys, "one", evict=True)
    assert [item["run_id"] for item in result["locations"]] == ["one"]
    assert [item["stage"] for item in result["warnings"]] == ["metadata_sync"]
    assert (remote / "records" / "one" / "commit.json").is_file()
    if fail_after_eviction:
        assert [item["run_id"] for item in result["evicted"]] == ["one"]
        assert not result.get("eviction_skipped")
        with pytest.raises(NotFoundError, match="unavailable"):
            store.object_path(asset_id)
        assert not (store.root / "runs" / "one").exists()
    else:
        assert result["evicted"] == []
        assert [item["run_id"] for item in result["eviction_skipped"]] == ["one"]
        assert store.object_path(asset_id).is_file()
        assert (store.root / "runs" / "one" / "result.txt").is_file()


def test_cli_batch_evicts_only_after_locations_synced_and_publishes_eviction_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    _seal(store, "one")
    remote_root = tmp_path / "remote"
    original = Store.evict_local

    def observe(self: Store, run_id: str, *, remote_verified: bool) -> dict[str, Any]:
        assert "location-verified" in _event_kinds(remote_root)
        return original(self, run_id, remote_verified=remote_verified)

    monkeypatch.setattr(Store, "evict_local", observe)
    result = _archive(store, remote_root, capsys, "one", evict=True)
    assert [item["run_id"] for item in result["evicted"]] == ["one"]
    assert "local-evicted" in _event_kinds(remote_root)
    assert len(_checkpoints(remote_root)) == 3


def test_cli_batch_initial_metadata_failure_has_no_commits_or_eviction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _store(tmp_path)
    asset_id = _seal(store, "one")
    remote_root = tmp_path / "remote"
    original = Remote._publish  # noqa: SLF001

    def reject_checkpoint(
        self: Remote, source: Path, relative: Path, digest: str
    ) -> None:
        if relative.parts[:2] == ("metadata", "checkpoints"):
            message = "initial metadata unavailable"
            raise OSError(message)
        original(self, source, relative, digest)

    monkeypatch.setattr(Remote, "_publish", reject_checkpoint)
    with pytest.raises(SystemExit, match="2"):
        _archive(store, remote_root, capsys, "one", evict=True)
    assert not (remote_root / "records" / "one" / "commit.json").exists()
    assert store.object_path(asset_id).is_file()
    assert (store.root / "runs" / "one" / "result.txt").is_file()
    assert "local-evicted" not in _event_kinds(store.root)


def test_batch_closes_parent_graph_when_parent_is_missed_by_directory_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    _seal(store, "parent")
    work = store.start_work("child")
    store.register_parent("child", "parent")
    (work / "result.txt").write_text("child payload\n")
    store.seal("child", {}, work)
    assert store.read_record("child")["parents"] == ["parent"]
    records = store.root / "records"
    original = Path.iterdir
    snapshots: list[list[str]] = []

    def omit_parent(self: Path) -> Iterator[Path]:
        paths = list(original(self))
        if self == records:
            paths = [path for path in paths if path.name != "parent"]
            snapshots.append([path.name for path in paths])
        return iter(paths)

    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "iterdir", omit_parent)
        with remote.archive_batch(store, ["child"]) as batch:
            batch.archive("child")
            store.label("child", "after-commit")
    assert len(snapshots) == 2
    assert all(snapshot == ["child"] for snapshot in snapshots)
    assert all(
        set(checkpoint["records"]) == {"parent", "child"}
        for checkpoint in _checkpoints(remote_root)
    )
    assert not (remote_root / "records" / "parent" / "commit.json").exists()
    target = Store(tmp_path / "reader", machine_id="reader")
    target.ensure_initialized("collection")
    assert remote.import_metadata(target)["records"] == 2
    assert target.read_record("child")["parents"] == ["parent"]
    assert target.projection("child")["labels"] == {"after-commit"}
    restored = remote.restore(target, "child")
    assert (restored / "result.txt").read_text() == "child payload\n"


def test_metadata_snapshot_ignores_completed_seal_staging_before_atomic_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    _seal(store, "selected")
    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)
    work = store.start_work("new-run")
    (work / "result.txt").write_text("new payload\n")
    original = store._fsync_dir  # noqa: SLF001
    staging_names: list[str] = []

    def snapshot_completed_staging(path: Path) -> None:
        if (
            path.parent == store.root / "records"
            and path.name.startswith(".new-run.")
            and (path / "complete.json").is_file()
            and not staging_names
        ):
            staging_names.append(path.name)
            assert not (store.root / "records" / "new-run").exists()
            remote.sync_metadata(store.root)
            checkpoints = _checkpoints(remote_root)
            assert len(checkpoints) == 1
            assert set(checkpoints[0]["records"]) == {"selected"}
            assert not (remote_root / "records" / path.name).exists()
            assert not (remote_root / "records" / "new-run").exists()
        original(path)

    monkeypatch.setattr(store, "_fsync_dir", snapshot_completed_staging)
    store.seal("new-run", {}, work)
    assert len(staging_names) == 1
    remote.sync_metadata(store.root)
    assert any(
        set(checkpoint["records"]) == {"selected", "new-run"}
        for checkpoint in _checkpoints(remote_root)
    )
    assert all(
        not (set(checkpoint["records"]) & set(staging_names))
        for checkpoint in _checkpoints(remote_root)
    )
    target = Store(tmp_path / "reader", machine_id="reader")
    target.ensure_initialized("collection")
    assert remote.import_metadata(target)["records"] == 2
    assert set(target.list_records()) == {"selected", "new-run"}

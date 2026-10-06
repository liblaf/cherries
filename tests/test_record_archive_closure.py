# Copyright (c) 2026 liblaf
"""Archive closures distinguish payload assets from record-control digests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from liblaf.cherries import _cli
from liblaf.cherries._remote import Remote
from liblaf.cherries.records import IntegrityError, NotFoundError, Store


def _seal(
    store: Store, run_id: str, files: dict[str, str], record: dict[str, object]
) -> None:
    work = store.start_work(run_id)
    for relative, value in files.items():
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)
    store.seal(run_id, record, work)


def _manifest_asset(store: Store, run_id: str, path: str) -> str:
    return next(
        item["asset_id"]
        for item in store.read_manifest(run_id)["files"]
        if item["path"] == path
    )


def test_archive_child_excludes_control_digests_and_restores_referenced_payloads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    _seal(
        source,
        "parent",
        {
            "outputs/input.txt": "parent payload\n",
            "outputs/companion.txt": "companion payload\n",
        },
        {},
    )
    parent_asset = _manifest_asset(source, "parent", "outputs/input.txt")
    companion_asset = _manifest_asset(source, "parent", "outputs/companion.txt")
    parent_record = source.read_record("parent")

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "support.txt").write_text("bundle payload\n")
    tree_id = source.put_tree(bundle)
    tree_entry = source.resolve_asset(tree_id)["tree"]["entries"][0]["asset_id"]

    _seal(
        source,
        "child",
        {
            "inputs/input.txt": "parent payload\n",
            "outputs/result.txt": "child payload\n",
        },
        {
            "parents": ["parent"],
            "input_bindings": [
                {
                    "asset_id": parent_asset,
                    "manifest_digest": parent_record["manifest_digest"],
                    "staged_path": "inputs/input.txt",
                    "members": [{"asset_id": companion_asset}],
                    "companions": [{"asset_id": companion_asset}],
                    "input_snapshot": [
                        {"asset_id": parent_asset},
                        {"asset_id": companion_asset},
                    ],
                }
            ],
            "bundles": [{"asset_id": tree_id, "staged_path": "bundles/support"}],
            "params": {
                "digest_like": "sha256:" + "1" * 64,
                "nested": {"tree_like": "sha256-tree:" + "2" * 64},
            },
        },
    )
    child_assets = {item["asset_id"] for item in source.read_manifest("child")["files"]}
    remote_root = tmp_path / "remote"
    remote = Remote(remote_root)

    remote.archive(source, "child")

    def browsed_run_ids(asset_id: str) -> set[str]:
        assert (
            _cli.main(
                ["--storage", str(source.root), "--json", "browse", "--asset", asset_id]
            )
            == 0
        )
        return {item["run_id"] for item in json.loads(capsys.readouterr().out)}

    assert browsed_run_ids(tree_id) == {"child"}
    assert browsed_run_ids(parent_record["manifest_digest"]) == set()
    assert browsed_run_ids("sha256:" + "1" * 64) == set()
    assert browsed_run_ids("sha256-tree:" + "2" * 64) == set()

    commit = json.loads((remote_root / "records" / "child" / "commit.json").read_text())
    assert set(commit["closure"]) == {
        parent_asset,
        companion_asset,
        tree_id,
        tree_entry,
        *child_assets,
    }
    assert parent_record["manifest_digest"] not in commit["closure"]
    assert "sha256:" + "1" * 64 not in commit["closure"]
    assert "sha256-tree:" + "2" * 64 not in commit["closure"]

    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")
    restored = remote.restore(target, "child")

    assert (restored / "inputs/input.txt").read_text() == "parent payload\n"
    assert (restored / "outputs/result.txt").read_text() == "child payload\n"
    assert (
        restored / "bundles/support" / "support.txt"
    ).read_text() == "bundle payload\n"
    assert target.object_path(parent_asset).is_file()
    assert target.object_path(companion_asset).is_file()
    assert target.tree_object_path(tree_id).is_file()
    plan = source.plan_prune(inventory_complete=True, maintenance=True)
    assert (
        str(source.object_path(tree_entry).relative_to(source.root))
        not in plan["objects"]
    )


def test_archive_rejects_missing_declared_payload_without_commit(
    tmp_path: Path,
) -> None:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    absent = "sha256:" + "0" * 64
    _seal(
        source,
        "run",
        {"outputs/result.txt": "result\n"},
        {"input_bindings": [{"asset_id": absent, "staged_path": "inputs/missing.txt"}]},
    )
    remote_root = tmp_path / "remote"

    with pytest.raises(NotFoundError, match="object unavailable"):
        Remote(remote_root).archive(source, "run")

    assert not (remote_root / "records" / "run" / "commit.json").exists()


def test_archive_rejects_malformed_declared_binding_members(tmp_path: Path) -> None:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    _seal(source, "parent", {"outputs/input.txt": "parent payload\n"}, {})
    asset_id = _manifest_asset(source, "parent", "outputs/input.txt")
    _seal(
        source,
        "run",
        {"outputs/result.txt": "result\n"},
        {
            "input_bindings": [
                {
                    "asset_id": asset_id,
                    "staged_path": "inputs/input.txt",
                    "members": "not-a-list",
                }
            ]
        },
    )
    remote_root = tmp_path / "remote"

    with pytest.raises(IntegrityError, match="asset"):
        Remote(remote_root).archive(source, "run")

    assert not (remote_root / "records" / "run" / "commit.json").exists()


def test_minimal_binding_without_asset_id_archives_and_restores(tmp_path: Path) -> None:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    _seal(
        source,
        "run",
        {"outputs/result.txt": "result\n"},
        {"input_bindings": [{"staged_path": "inputs/no-asset.txt"}]},
    )
    remote_root = tmp_path / "remote"
    Remote(remote_root).archive(source, "run")

    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")
    restored = Remote(remote_root).restore(target, "run")

    assert (restored / "outputs/result.txt").read_text() == "result\n"


def test_bootstrap_recovers_sealed_child_with_control_manifest_digest(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store", machine_id="source-machine")
    store.ensure_initialized("collection")
    _seal(store, "parent", {"outputs/input.txt": "parent payload\n"}, {})
    parent_asset = _manifest_asset(store, "parent", "outputs/input.txt")
    parent_record = store.read_record("parent")
    _seal(
        store,
        "child",
        {"outputs/result.txt": "child payload\n"},
        {
            "parents": ["parent"],
            "input_bindings": [
                {
                    "asset_id": parent_asset,
                    "manifest_digest": parent_record["manifest_digest"],
                    "staged_path": "inputs/input.txt",
                }
            ],
        },
    )
    work = store.root / "work" / "child"
    work.mkdir(parents=True)
    (work / ".cherries-work.json").write_text(
        json.dumps({"run_id": "child", "metadata": {}})
    )
    pending = store.root / "pending" / "child.json"
    pending.write_text(json.dumps({"run_id": "child", "roots": [], "metadata": {}}))

    Store(store.root).ensure_initialized()

    assert not work.exists()
    assert not pending.exists()

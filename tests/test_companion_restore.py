# Copyright (c) 2026 liblaf
"""Companion tree bundles have a directory mount and a file-facing primary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from liblaf.cherries import _access, _cli
from liblaf.cherries._remote import Remote
from liblaf.cherries.records import IntegrityError, Store


def _tree(store: Store, root: Path) -> str:
    root.mkdir()
    (root / "mesh.vtu").write_text("mesh payload\n")
    (root / "mesh.landmarks.json").write_text('{"points":[1,2]}\n')
    return store.put_tree(root)


def _companion_record(tmp_path: Path) -> tuple[Store, Remote, str]:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    companion_tree = _tree(source, tmp_path / "companion-tree")
    empty_tree_root = tmp_path / "empty-tree"
    (empty_tree_root / "nested" / "empty").mkdir(parents=True)
    empty_tree = source.put_tree(empty_tree_root)
    work = source.start_work("run")
    (work / "outputs").mkdir()
    (work / "outputs" / "mesh.vtu").write_text("mesh payload\n")
    (work / "outputs" / "mesh.landmarks.json").write_text('{"points":[1,2]}\n')
    (work / "inputs" / "mesh-tree").mkdir(parents=True)
    (work / "inputs" / "mesh-tree" / "mesh.vtu").write_text("mesh payload\n")
    (work / "inputs" / "mesh-tree" / "mesh.landmarks.json").write_text(
        '{"points":[1,2]}\n'
    )
    source.seal(
        "run",
        {
            "bundles": [
                {
                    "asset_id": companion_tree,
                    "kind": "companions",
                    "path": "outputs/mesh.vtu",
                    "primary": "mesh.vtu",
                },
                {
                    "asset_id": empty_tree,
                    "kind": "directory",
                    "path": "outputs/directory-output",
                },
            ],
            "input_bindings": [
                {
                    "asset_id": companion_tree,
                    "directory": True,
                    "staged_path": "inputs/mesh-tree",
                }
            ],
        },
        work,
    )
    remote = Remote(tmp_path / "remote")
    remote.archive(source, "run")
    return source, remote, "run"


def _assert_materialized(root: Path) -> None:
    assert (root / "outputs" / "mesh.vtu").is_file()
    assert (root / "outputs" / "mesh.vtu").read_text() == "mesh payload\n"
    assert (root / "outputs" / "mesh.landmarks.json").read_text() == (
        '{"points":[1,2]}\n'
    )
    assert (root / "outputs" / "directory-output" / "nested" / "empty").is_dir()
    assert (root / "inputs" / "mesh-tree").is_dir()
    assert (root / "inputs" / "mesh-tree" / "mesh.vtu").read_text() == (
        "mesh payload\n"
    )
    assert (root / "inputs" / "mesh-tree" / "mesh.landmarks.json").read_text() == (
        '{"points":[1,2]}\n'
    )


def test_remote_restore_mounts_companion_tree_at_parent_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, remote, run_id = _companion_record(tmp_path)
    record = source.read_record(run_id)["record"]
    companion = record["bundles"][0]
    assert companion == {
        "asset_id": companion["asset_id"],
        "kind": "companions",
        "path": "outputs/mesh.vtu",
        "primary": "mesh.vtu",
    }
    assert {
        entry["path"]
        for entry in source.resolve_asset(companion["asset_id"])["tree"]["entries"]
    } == {
        "mesh.landmarks.json",
        "mesh.vtu",
    }

    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized(source.collection_id)
    restored = remote.restore(target, run_id)
    assert remote.restore(target, run_id) == restored
    _assert_materialized(restored)

    monkeypatch.setattr(_access, "configured_remote", lambda _project: None)
    with _access.open_run(run_id, store=target) as reader:
        primary = reader.path("outputs/mesh.vtu")
        assert primary.is_file()
        assert primary.read_text() == "mesh payload\n"
        assert (
            primary.with_suffix(".landmarks.json").read_text() == '{"points":[1,2]}\n'
        )
        staged = reader.path("inputs/mesh-tree")
        assert staged.is_dir()
        assert (staged / "mesh.vtu").read_text() == "mesh payload\n"


def test_remote_accessor_fetches_companion_tree_at_its_file_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, remote, run_id = _companion_record(tmp_path)
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized(source.collection_id)
    remote.import_metadata(target, run_id)
    monkeypatch.setattr(_access, "configured_remote", lambda _project: remote)

    with _access.open_run(run_id, store=target) as reader:
        primary = reader.path("outputs/mesh.vtu")
        assert primary.is_file()
        assert primary.read_text() == "mesh payload\n"
        assert (
            primary.with_suffix(".landmarks.json").read_text() == '{"points":[1,2]}\n'
        )


def test_companion_binding_validation_fails_before_writing_a_view(
    tmp_path: Path,
) -> None:
    source, _remote, run_id = _companion_record(tmp_path)
    binding = source.read_record(run_id)["record"]["bundles"][0]
    bad_tree_root = tmp_path / "bad-tree"
    bad_tree_root.mkdir()
    (bad_tree_root / "mesh.vtu").write_text("conflicting mesh\n")
    conflicting_tree = source.put_tree(bad_tree_root)
    missing_primary_root = tmp_path / "missing-primary"
    missing_primary_root.mkdir()
    (missing_primary_root / "only-landmarks.json").write_text("{}\n")
    missing_primary_tree = source.put_tree(missing_primary_root)

    invalid_bindings = [
        {**binding, "primary": "wrong.vtu"},
        {**binding, "asset_id": missing_primary_tree},
        {**binding, "asset_id": conflicting_tree},
        {
            **binding,
            "directory": True,
            "staged_path": "outputs/mesh.vtu",
        },
    ]
    expected_messages = [
        "logical primary",
        "primary must be a declared",
        "member conflicts with manifest",
        "directory conflicts with manifest",
    ]
    for invalid, message in zip(invalid_bindings, expected_messages, strict=True):
        with pytest.raises(IntegrityError, match=message):
            source.materialize_tree_binding(run_id, invalid)
        assert not (source.root / "runs" / run_id).exists()


def test_cli_path_prefers_staged_directory_tree_location_locally_and_remotely(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    input_source = tmp_path / "input-source"
    (input_source / "nested" / "empty").mkdir(parents=True)
    tree_id = source.put_tree(input_source)
    work = source.start_work("run")
    (work / "inputs" / "local-dir" / "nested" / "empty").mkdir(parents=True)
    (work / "outputs").mkdir()
    (work / "outputs" / "receipt.txt").write_text("receipt\n")
    source.seal(
        "run",
        {
            "input_bindings": [
                {
                    "asset_id": tree_id,
                    "directory": True,
                    "path": "outputs/source-dir",
                    "staged_path": "inputs/local-dir",
                }
            ]
        },
        work,
    )
    remote = Remote(tmp_path / "remote")
    remote.archive(source, "run")
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized(source.collection_id)

    def path_and_release(store: Store, *, remote_path: Path | None = None) -> Path:
        capsys.readouterr()
        args = [
            "--storage",
            str(store.root),
            "--json",
            "path",
            "run",
            "inputs/local-dir",
        ]
        if remote_path is not None:
            args.extend(["--remote", str(remote_path)])
        assert _cli.main(args) == 0
        result = json.loads(capsys.readouterr().out)
        selected = Path(result["path"])
        assert (
            _cli.main(
                [
                    "--storage",
                    str(store.root),
                    "--json",
                    "path",
                    "--release",
                    result["lease"],
                ]
            )
            == 0
        )
        capsys.readouterr()
        return selected

    local = path_and_release(source)
    assert local == source.root / "runs" / "run" / "inputs" / "local-dir"
    assert (local / "nested" / "empty").is_dir()
    fetched = path_and_release(target, remote_path=Path(remote.remote))
    assert fetched == target.root / "runs" / "run" / "inputs" / "local-dir"
    assert (fetched / "nested" / "empty").is_dir()


def test_local_cli_restore_mounts_companion_tree_and_repeats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _remote, run_id = _companion_record(tmp_path)

    for _ in range(2):
        capsys.readouterr()
        assert _cli.main(["--storage", str(source.root), "restore", run_id]) == 0
        _assert_materialized(source.root / "runs" / run_id)

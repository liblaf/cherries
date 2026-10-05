# Copyright (c) 2026 liblaf
from __future__ import annotations

import json
from pathlib import Path

import pytest

from liblaf.cherries import _access
from liblaf.cherries.records import Store


def series_record(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store")
    work = store.start_work("series-record")
    (work / "outputs").mkdir()
    (work / "outputs/mesh.series").write_text(
        '{"file-series-version":"1.0","files":[{"name":"mesh-0.vtu","time":0}]}'
    )
    (work / "outputs/mesh-0.vtu").write_text("mesh")
    store.seal("series-record", {"kind": "experiment"}, work)
    return store


def test_accessor_materializes_series_closure_and_releases_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_access, "configured_remote", lambda _project: None)
    store = series_record(tmp_path)
    with _access.open_run("series-record", store=store) as record:
        assert store.projection("series-record")["holds"]
        series = record.path("outputs/mesh.series")
        assert (series.parent / "mesh-0.vtu").read_text() == "mesh"
        with pytest.raises(ValueError, match="contained"):
            record.path("../escape")
    assert not store.projection("series-record")["holds"]
    with pytest.raises(RuntimeError, match="closed"):
        record.path("outputs/mesh.series")


def test_workspace_retains_source_after_reader_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_access, "configured_remote", lambda _project: None)
    store = series_record(tmp_path)
    workspace = tmp_path / "analysis"
    workspace.mkdir()
    (workspace / "analysis.json").write_text(
        json.dumps({"workspace_id": "meeting", "sources": []})
    )
    with _access.open_run("series-record", store=store, workspace=workspace):
        pass
    assert "analysis:meeting" in store.projection("series-record")["holds"]
    assert json.loads((workspace / "analysis.json").read_text())["sources"] == [
        "series-record"
    ]


def test_accessor_opens_empty_directory_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_access, "configured_remote", lambda _project: None)
    store = Store(tmp_path / "store")
    work = store.start_work("run")
    directory = work / "outputs" / "tree"
    (directory / "empty").mkdir(parents=True)
    tree = store.put_tree(directory)
    store.seal("run", {"bundles": [{"path": "outputs/tree", "asset_id": tree}]}, work)
    with _access.open_run("run", store=store) as reader:
        assert (reader.path("outputs/tree") / "empty").is_dir()


def test_failed_workspace_binding_does_not_leave_a_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_access, "configured_remote", lambda _project: None)
    store = series_record(tmp_path)
    workspace = tmp_path / "analysis"
    workspace.mkdir()
    config = workspace / "analysis.json"
    config.write_text(json.dumps({"workspace_id": "meeting", "sources": []}))
    original = config.read_bytes()
    original_replace = Path.replace

    def fail_replace(source: Path, target: Path) -> Path:
        if target == config:
            message = "disk full"
            raise OSError(message)
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        _access.open_run("series-record", store=store, workspace=workspace)
    assert config.read_bytes() == original
    assert not store.projection("series-record")["holds"]


def test_workspace_close_preserves_an_active_accessor_reader_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from liblaf.cherries import _cli

    monkeypatch.setattr(_access, "configured_remote", lambda _project: None)
    store = series_record(tmp_path)
    workspace = tmp_path / "analysis"
    workspace.mkdir()
    (workspace / "analysis.json").write_text(
        json.dumps({"workspace_id": "meeting", "sources": []})
    )
    with _access.open_run("series-record", store=store, workspace=workspace) as reader:
        _cli.main(["--storage", str(store.root), "analysis", "close", str(workspace)])
        assert store.projection("series-record")["holds"]
        assert reader.path("outputs/mesh.series").is_file()
    assert not store.projection("series-record")["holds"]


def test_workspace_close_during_accessor_open_preserves_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_access, "configured_remote", lambda _project: None)
    store = series_record(tmp_path)
    workspace = tmp_path / "analysis"
    workspace.mkdir()
    (workspace / "analysis.json").write_text(
        json.dumps({"workspace_id": "meeting", "sources": []})
    )
    original_bind = _access.RunAccessor._bind_workspace  # noqa: SLF001
    eviction_attempts: list[dict[str, object]] = []

    def close_after_binding(reader: _access.RunAccessor, folder: Path) -> None:
        original_bind(reader, folder)
        store.release_hold("series-record", "analysis:meeting")
        eviction_attempts.append(
            store.evict_local("series-record", remote_verified=True)
        )

    monkeypatch.setattr(_access.RunAccessor, "_bind_workspace", close_after_binding)
    with _access.open_run("series-record", store=store, workspace=workspace) as reader:
        assert not eviction_attempts[0]["allowed"]
        assert reader.path("outputs/mesh.series").is_file()
    assert not store.projection("series-record")["holds"]

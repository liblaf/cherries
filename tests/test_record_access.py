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

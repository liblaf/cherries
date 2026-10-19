# Copyright (c) 2026 liblaf
"""Explicit remote origins import their lineage without unrelated run history."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from liblaf.cherries import _access, _settings
from liblaf.cherries._remote import Remote
from liblaf.cherries.core.assets import AssetsManager
from liblaf.cherries.records import NotFoundError, Store


def _lineage(tmp_path: Path) -> tuple[Store, Remote, Store]:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    for run_id in ("ancestor", "selected-result", "unrelated"):
        work = source.start_work(run_id)
        if run_id == "selected-result":
            source.register_parent(run_id, "ancestor")
        (work / "output.txt").write_text(run_id)
        source.seal(run_id, {}, work)
        source.append_event("note", run_id, {"value": f"{run_id} note"})
    remote = Remote(tmp_path / "remote")
    remote.archive(source, "selected-result")
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")
    return source, remote, target


def _preserved_state(store: Store) -> dict[Path, bytes]:
    return {
        path.relative_to(store.root): path.read_bytes()
        for directory in ("work", "pending")
        for path in (store.root / directory).rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("requested", ["selected-result", "selected-r"])
def test_accessor_imports_only_explicit_remote_lineage_and_preserves_old_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requested: str
) -> None:
    _source, remote, target = _lineage(tmp_path)
    old_work = target.start_work("historical-failed")
    (old_work / "evidence.txt").write_text("preserve historical work")
    before = _preserved_state(target)
    monkeypatch.setattr(_access, "configured_remote", lambda _project: remote)

    with _access.open_run(requested, store=target) as reader:
        assert reader.run_id == "selected-result"
        assert reader.path("output.txt").read_text() == "selected-result"
        assert target.projection("selected-result")["holds"] == {reader.reason}
        assert target.list_records() == ["ancestor", "selected-result"]
        assert target.projection("ancestor")["notes"] == [{"value": "ancestor note"}]

    assert target.projection("selected-result")["holds"] == set()
    assert _preserved_state(target) == before
    assert not any(
        json.loads(path.read_bytes())["subject"] == "unrelated"
        for path in (target.root / "metadata" / "events").glob("*/*.json")
    )


@pytest.mark.parametrize("origin", ["run-full", "run-prefix", "sha-full", "sha-prefix"])
def test_input_with_explicit_origin_imports_only_source_ancestry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    source, remote, target = _lineage(tmp_path)
    monkeypatch.setattr(_settings, "configured_remote", lambda _project: remote)
    work = target.start_work("consumer")
    manager = AssetsManager(
        working_dir=work,
        plugins=SimpleNamespace(log_asset=lambda *_args, **_kwargs: None),
        active=True,
        store=target,
        run_id="consumer",
    )
    producer = "selected-r" if origin.endswith("prefix") else "selected-result"
    if origin.startswith("run"):
        staged = manager.input(f"run:{producer}/output.txt")
    else:
        asset_id = source.read_manifest("selected-result")["files"][0]["asset_id"]
        staged = manager.input(asset_id, source_run=producer)

    assert staged.read_text() == "selected-result"
    assert target.list_records() == ["ancestor", "selected-result"]
    assert manager.bindings[0]["run_id"] == "selected-result"
    assert target.projection("selected-result")["holds"] == set()
    assert not any(
        json.loads(path.read_bytes())["subject"] == "unrelated"
        for path in (target.root / "metadata" / "events").glob("*/*.json")
    )


def test_remote_prefix_ambiguity_rejects_before_any_local_install(
    tmp_path: Path,
) -> None:
    source, remote, target = _lineage(tmp_path)
    work = source.start_work("selected-rival")
    (work / "output.txt").write_text("different")
    source.seal("selected-rival", {}, work)
    remote.sync_metadata(source.root)

    with pytest.raises(NotFoundError, match="exactly one"):
        remote.import_metadata(target, "selected-r")

    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


def test_remote_exact_id_wins_over_longer_matching_id(tmp_path: Path) -> None:
    source, remote, target = _lineage(tmp_path)
    work = source.start_work("selected-result-longer")
    (work / "output.txt").write_text("different")
    source.seal("selected-result-longer", {}, work)
    remote.sync_metadata(source.root)

    assert remote.import_metadata(target, "selected-result")["records"] == 2
    assert target.list_records() == ["ancestor", "selected-result"]

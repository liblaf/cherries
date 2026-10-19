# Copyright (c) 2026 liblaf
"""Explicit remote origins import their lineage without unrelated run history."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from liblaf.cherries import _access, _settings
from liblaf.cherries._remote import IntegrityError, Remote, RemoteError
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


@pytest.mark.parametrize("identifier", ["", "../escape", "run/escape"])
def test_invalid_selected_remote_id_cannot_install_metadata(
    tmp_path: Path, identifier: str
) -> None:
    _source, remote, target = _lineage(tmp_path)

    with pytest.raises(RemoteError, match="not contained"):
        remote.import_metadata(target, identifier)

    assert target.list_records() == []
    assert not list((target.root / "metadata" / "events").glob("*/*.json"))


@pytest.mark.parametrize("route", ["import", "accessor", "input"])
def test_selected_lineage_rejects_conflicting_existing_parent_before_child_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """A locally existing parent ID cannot silently substitute another receipt."""
    _source, remote, target = _lineage(tmp_path)
    work = target.start_work("ancestor")
    (work / "output.txt").write_text("different local ancestor receipt")
    target.seal("ancestor", {}, work)
    before = {
        path.relative_to(target.root): path.read_bytes()
        for area in ("records", "metadata")
        for path in (target.root / area).rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(_access, "configured_remote", lambda _project: remote)
    monkeypatch.setattr(_settings, "configured_remote", lambda _project: remote)
    manager = AssetsManager(
        working_dir=target.start_work("consumer"),
        plugins=SimpleNamespace(log_asset=lambda *_args, **_kwargs: None),
        active=True,
        store=target,
        run_id="consumer",
    )

    def attempt_import() -> None:
        if route == "import":
            remote.import_metadata(target, "selected-result")
        elif route == "accessor":
            with _access.open_run("selected-result", store=target):
                pass
        else:
            manager.input("run:selected-result/output.txt")

    with pytest.raises(IntegrityError, match="conflict"):
        attempt_import()

    assert target.list_records() == ["ancestor"]
    after = {
        path.relative_to(target.root): path.read_bytes()
        for area in ("records", "metadata")
        for path in (target.root / area).rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("route", ["import", "accessor", "input-run", "input-sha"])
@pytest.mark.parametrize("exact", [False, True])
def test_remote_origin_resolution_respects_local_prefix_collisions_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, *, exact: bool
) -> None:
    """A remote unique prefix does not override local ambiguity; exact IDs work."""
    source, remote, target = _lineage(tmp_path)
    requested = "selected-result" if exact else "selected-r"
    for suffix in ("-local-one", "-local-two"):
        run_id = requested + suffix
        work = target.start_work(run_id)
        (work / "output.txt").write_text(run_id)
        target.seal(run_id, {}, work)
    initial_ids = target.list_records()
    before = {
        path.relative_to(target.root): path.read_bytes()
        for area in ("records", "metadata")
        for path in (target.root / area).rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(_access, "configured_remote", lambda _project: remote)
    monkeypatch.setattr(_settings, "configured_remote", lambda _project: remote)
    manager = AssetsManager(
        working_dir=target.start_work("consumer"),
        plugins=SimpleNamespace(log_asset=lambda *_args, **_kwargs: None),
        active=True,
        store=target,
        run_id="consumer",
    )
    asset_id = source.read_manifest("selected-result")["files"][0]["asset_id"]

    def attempt_import() -> None:
        if route == "import":
            remote.import_metadata(target, requested)
        elif route == "accessor":
            with _access.open_run(requested, store=target) as reader:
                assert reader.run_id == "selected-result"
        elif route == "input-run":
            assert (
                manager.input(f"run:{requested}/output.txt").read_text()
                == "selected-result"
            )
        else:
            assert (
                manager.input(asset_id, source_run=requested).read_text()
                == "selected-result"
            )

    if exact:
        attempt_import()
        assert target.list_records() == sorted(
            [*initial_ids, "ancestor", "selected-result"]
        )
        assert not target.projection("selected-result")["holds"]
    else:
        with pytest.raises(NotFoundError, match="exactly one"):
            attempt_import()
        assert target.list_records() == initial_ids
        after = {
            path.relative_to(target.root): path.read_bytes()
            for area in ("records", "metadata")
            for path in (target.root / area).rglob("*")
            if path.is_file()
        }
        assert after == before


def test_matching_local_parent_is_reverified_without_rewriting_its_controls(
    tmp_path: Path,
) -> None:
    _source, remote, target = _lineage(tmp_path)
    assert remote.import_metadata(target, "ancestor") == {"records": 1, "events": 2}
    controls = {
        path: path.read_bytes()
        for path in (target.root / "records" / "ancestor").glob("*.json")
    }

    assert remote.import_metadata(target, "selected-result") == {
        "records": 1,
        "events": 2,
    }
    assert target.list_records() == ["ancestor", "selected-result"]
    assert all(path.read_bytes() == data for path, data in controls.items())
    assert len(target.projection("ancestor")["notes"]) == 1


@pytest.mark.parametrize("invalid", [b"{", b"\xff"])
def test_malformed_local_parent_completion_blocks_child_before_any_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: bytes
) -> None:
    _source, remote, target = _lineage(tmp_path)
    remote.import_metadata(target, "ancestor")
    completion = target.root / "records" / "ancestor" / "complete.json"
    completion.write_bytes(invalid)
    before = {
        path.relative_to(target.root): path.read_bytes()
        for area in ("records", "metadata")
        for path in (target.root / area).rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(_access, "configured_remote", lambda _project: remote)

    with pytest.raises(
        IntegrityError, match="local completion metadata is invalid"
    ) as caught:
        _access.open_run("selected-result", store=target)

    assert isinstance(
        caught.value.__cause__, (json.JSONDecodeError, UnicodeDecodeError)
    )
    assert target.list_records() == ["ancestor"]
    after = {
        path.relative_to(target.root): path.read_bytes()
        for area in ("records", "metadata")
        for path in (target.root / area).rglob("*")
        if path.is_file()
    }
    assert after == before

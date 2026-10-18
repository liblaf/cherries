# Copyright (c) 2026 liblaf
"""Reading a collection preserves retained work unless recovery is opted into."""

from __future__ import annotations

import errno
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from liblaf import cherries
from liblaf.cherries import _cli, _settings
from liblaf.cherries.core import Run
from liblaf.cherries.records import Store, _store


def _snapshot(root: Path) -> dict[str, tuple[int, bytes | str | None]]:
    if not root.exists():
        return {}
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        mode = path.lstat().st_mode
        content = (
            path.readlink().as_posix()
            if stat.S_ISLNK(mode)
            else path.read_bytes()
            if stat.S_ISREG(mode)
            else None
        )
        result[path.relative_to(root).as_posix()] = (mode, content)
    return result


def _leftover(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, pending: bool = False
) -> tuple[Store, Path]:
    """Inject only the disposable producer's postcommit cleanup failure."""
    store = Store(root)
    work = store.start_work("run")
    (work / "outputs").mkdir()
    (work / "outputs/result.txt").write_text("verified payload\n")
    (work / "scratch/nested").mkdir(parents=True)
    (work / "scratch/nested/memory.txt").write_text("preserve this diagnostic\n")
    original_rmtree = _store.shutil.rmtree
    original_unlink = Path.unlink

    def rmtree(path: Path, *args: Any, **kwargs: Any) -> None:
        if Path(path) == work:
            raise OSError(errno.EACCES, "injected producer cleanup failure")
        original_rmtree(path, *args, **kwargs)

    def unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == root / "pending/run.json":
            raise OSError(errno.EIO, "injected producer pending cleanup failure")
        original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(_store.shutil, "rmtree", rmtree)
        if pending:
            patch.setattr(Path, "unlink", unlink)
        result = store.seal("run", {}, work)
    assert result["committed"] is True
    assert result["warnings"][0]["stage"] == (
        "pending_cleanup" if pending else "work_cleanup"
    )
    assert work.is_dir()
    return store, work


@pytest.mark.parametrize("policy", [None, False])
@pytest.mark.parametrize("pending", [False, True])
def test_default_reader_preserves_full_retained_work_and_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy: bool | None,
    pending: bool,
) -> None:
    producer, work = _leftover(tmp_path / "store", monkeypatch, pending=pending)
    work_before = _snapshot(work)
    pending_before = _snapshot(producer.root / "pending")
    controls_before = _snapshot(producer.root / "records")
    events_before = _snapshot(producer.root / "metadata/events")
    reader_store = (
        Store(producer.root)
        if policy is None
        else Store(producer.root, auto_recover=policy)
    )
    for _ in range(2):
        reader_store.ensure_initialized()
        with cherries.open_run("run", store=reader_store) as reader:
            assert reader.path("outputs/result.txt").read_text() == "verified payload\n"
        assert reader.closed
        assert not reader_store.projection("run")["holds"]
    assert _snapshot(work) == work_before
    assert _snapshot(producer.root / "pending") == pending_before
    assert _snapshot(producer.root / "records") == controls_before
    events_after = _snapshot(producer.root / "metadata/events")
    assert all(events_after[path] == value for path, value in events_before.items())
    new_events = [
        json.loads(value[1])
        for path, value in events_after.items()
        if path not in events_before and isinstance(value[1], bytes)
    ]
    assert len(new_events) == 4
    assert {event["kind"] for event in new_events} == {"hold"}


@pytest.mark.parametrize(
    "condition", ["owned-dead", "live", "missing-marker", "corrupt-payload"]
)
def test_optin_recovery_keeps_existing_ownership_and_integrity_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    producer, work = _leftover(tmp_path / "store", monkeypatch, pending=True)
    if condition == "live":
        (work / ".cherries-work.json").write_text(
            json.dumps({"run_id": "run", "metadata": {"pid": os.getpid()}})
        )
    elif condition == "missing-marker":
        (work / ".cherries-work.json").unlink()
    elif condition == "corrupt-payload":
        asset = producer.read_manifest("run")["files"][0]["asset_id"]
        producer.object_path(asset).write_bytes(b"corrupted")
    before = _snapshot(work)
    pending = producer.root / "pending/run.json"
    pending_before = pending.read_bytes()
    store = Store(producer.root, auto_recover=True)
    store.ensure_initialized()
    store.ensure_initialized()
    if condition == "owned-dead":
        assert not work.exists()
        assert not pending.exists()
    else:
        assert _snapshot(work) == before
        assert pending.read_bytes() == pending_before


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_store_requires_a_real_boolean_before_mutating_root(
    tmp_path: Path, value: Any
) -> None:
    root = tmp_path / "absent"
    with pytest.raises((TypeError, ValueError), match="auto_recover"):
        Store(root, auto_recover=value)
    assert not root.exists()


def test_store_policy_is_readonly_and_default_false(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    assert store.auto_recover is False
    with pytest.raises(AttributeError):
        store.auto_recover = True
    assert not store.root.exists()


def _project(tmp_path: Path, policy: str = "false") -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "cherries.toml").write_text(
        f'[collection]\nstorage="data"\nauto_recover={policy}\n'
    )
    return project


@pytest.mark.parametrize("policy", ["true", "false"])
def test_configured_store_resolves_subdirectory_and_local_override(
    tmp_path: Path, policy: str
) -> None:
    project = _project(tmp_path, "true" if policy == "false" else "false")
    (project / "cherries.local.toml").write_text(
        f"[collection]\nauto_recover={policy}\n"
    )
    child = project / "exp/study"
    child.mkdir(parents=True)
    store = _settings.configured_store(child, machine_id="test-machine")
    assert store.root == project / "data"
    assert store.auto_recover is (policy == "true")
    assert not store.root.exists()


@pytest.mark.parametrize("value", ['"false"', "0", "[]", "{}"])
def test_invalid_project_policy_is_rejected_before_store_mutation(
    tmp_path: Path, value: str
) -> None:
    project = _project(tmp_path, value)
    with pytest.raises((TypeError, ValueError), match="auto_recover"):
        _settings.configured_store(project)
    assert not (project / "data").exists()


@pytest.mark.parametrize("policy", [False, True])
def test_cli_project_dir_applies_policy_with_explicit_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    policy: bool,
) -> None:
    project = _project(tmp_path, str(policy).lower())
    _, work = _leftover(tmp_path / "explicit-root", monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert (
        _cli.main(
            [
                "--project-dir",
                str(project),
                "--storage",
                str(work.parent.parent),
                "--json",
                "init",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert work.exists() is (not policy)


@pytest.mark.parametrize("policy", [False, True])
def test_run_project_override_uses_project_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, policy: bool
) -> None:
    project = _project(tmp_path, str(policy).lower())
    _, work = _leftover(tmp_path / "explicit-root", monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    script = elsewhere / "experiment.py"
    script.write_text("from liblaf import cherries\n")
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(sys, "argv", [str(script)])
    monkeypatch.delenv("CHERRIES_PARENT_RUN", raising=False)
    run = Run(store_root=work.parent.parent)
    run.project_dir = project
    run.repo = None
    run.start()
    try:
        assert run.store is not None
        assert run.store.auto_recover is policy
        assert work.exists() is (not policy)
        run.output("result.txt").write_text("new experiment\n")
        run.end()
    finally:
        if run.active:
            run.end(exc=RuntimeError("test teardown"))


@pytest.mark.parametrize("policy", [False, True])
def test_default_accessor_reads_config_but_provided_store_keeps_its_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, policy: bool
) -> None:
    project = _project(tmp_path, str(policy).lower())
    producer, work = _leftover(project / "data", monkeypatch)
    monkeypatch.chdir(project)
    # Explicit supplied Store remains authoritative even when config disagrees.
    with cherries.open_run(
        "run", store=Store(producer.root, auto_recover=not policy)
    ) as reader:
        assert reader.store.auto_recover is (not policy)
    assert work.exists() is policy
    # Fresh independent producer exercises config-selected default accessor.
    other, other_work = _leftover(tmp_path / "second-root", monkeypatch)
    monkeypatch.setenv("CHERRIES_STORAGE", str(other.root))
    with cherries.open_run("run") as reader:
        assert reader.store.auto_recover is policy
        assert reader.path("outputs/result.txt").read_text() == "verified payload\n"
    assert reader.closed
    assert other_work.exists() is (not policy)


def test_optin_seal_does_not_recover_its_own_in_progress_publication(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "store", auto_recover=True)
    work = store.start_work("run")
    marker = json.loads((work / ".cherries-work.json").read_text())
    assert "pid" not in marker["metadata"]
    output = work / "outputs/result.txt"
    output.parent.mkdir()
    output.write_text("committed payload\n")

    result = store.seal("run", {}, work)

    assert result["committed"] is True
    assert not result.get("warnings")
    assert not work.exists()
    assert not (store.root / "pending/run.json").exists()
    events = [
        json.loads(path.read_text())
        for path in (store.root / "metadata/events").glob("*/*.json")
    ]
    assert len(events) == 1
    assert events[0]["kind"] == "sealed"
    assert events[0]["value"]["root_digest"] == result["root_digest"]
    assert (
        store.materialize("run", "outputs/result.txt").read_text()
        == "committed payload\n"
    )

# Copyright (c) 2026 liblaf
"""Selected native imports keep durable writes proportional to their lineage."""

from __future__ import annotations

import errno
import json
import os
import stat
from collections import Counter
from pathlib import Path

import pytest

from liblaf.cherries._remote import IntegrityError, Remote
from liblaf.cherries.records import IntegrityError as StoreIntegrityError
from liblaf.cherries.records import Store, canonical_json


def _native_archive(tmp_path: Path) -> tuple[Remote, Store]:
    source = Store(tmp_path / "source", machine_id="source-machine")
    source.ensure_initialized("collection")
    for run_id in ("selected", "unrelated"):
        work = source.start_work(run_id)
        (work / "output.txt").write_text(run_id)
        source.seal(run_id, {}, work)
    for number in range(48):
        source.append_event("note", "unrelated", {"value": str(number)})
    for number in range(128):
        source.append_event("note", "selected", {"value": f"finding {number}"})
    remote = Remote(tmp_path / "archive")
    remote.archive(source, "selected")
    target = Store(tmp_path / "target", machine_id="target-machine")
    target.ensure_initialized("collection")
    return remote, target


def test_selected_import_writes_only_requested_metadata_and_repeat_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unrelated history may require proof reads, never unrelated durable writes."""
    remote, target = _native_archive(tmp_path)
    writes: list[Path] = []
    syncs: list[Path] = []
    atomic_bytes = target._atomic_bytes  # noqa: SLF001
    fsync_dir = target._fsync_dir  # noqa: SLF001

    def track_write(path: Path, data: bytes, **kwargs: bool) -> None:
        writes.append(path)
        atomic_bytes(path, data, **kwargs)

    def track_sync(path: Path) -> None:
        syncs.append(path)
        fsync_dir(path)

    monkeypatch.setattr(target, "_atomic_bytes", track_write)
    monkeypatch.setattr(target, "_fsync_dir", track_sync)

    imported = remote.import_metadata(target, "selected")

    assert imported == {"records": 1, "events": 129}
    assert target.list_records() == ["selected"]
    assert len(target.projection("selected")["notes"]) == 128
    assert (
        Counter(path.relative_to(target.root).parts[0] for path in writes)["records"]
        == 3
    )
    metadata_syncs = [path for path in syncs if "metadata" in path.parts]
    assert 1 <= len(metadata_syncs) <= 3
    assert len(list((target.root / "metadata" / "events").glob("*/*.json"))) == 129
    assert not list((target.root / "objects" / "sha256").glob("*/*"))
    writes.clear()
    syncs.clear()

    assert remote.import_metadata(target, "selected") == {"records": 0, "events": 0}
    assert writes == []
    assert syncs == [
        target.root / "metadata" / "events" / "source-machine",
        target.root / "metadata" / "events",
        target.root / "metadata",
        target.root,
    ]


@pytest.mark.parametrize("already_imported", [False, True])
def test_unrelated_checkpoint_event_tamper_fails_before_selected_install(
    tmp_path: Path,
    *,
    already_imported: bool,
) -> None:
    """A selected request must still validate every checkpoint-bound event."""
    remote, target = _native_archive(tmp_path)
    assert remote.local is not None
    if already_imported:
        remote.import_metadata(target, "selected")
    before = {
        path.relative_to(target.root): path.read_bytes()
        for directory in ("records", "metadata")
        for path in (target.root / directory).rglob("*")
        if path.is_file()
    }
    unrelated = next(
        path
        for path in (remote.local / "metadata" / "events").glob("*/*.json")
        if b'"subject":"unrelated"' in path.read_bytes()
    )
    unrelated.write_bytes(unrelated.read_bytes() + b" ")

    with pytest.raises(IntegrityError, match=r"event.*checkpoint"):
        remote.import_metadata(target, "selected")

    after = {
        path.relative_to(target.root): path.read_bytes()
        for directory in ("records", "metadata")
        for path in (target.root / directory).rglob("*")
        if path.is_file()
    }
    assert after == before


def test_cli_show_remote_keeps_unrelated_native_records_and_history_unimported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The normal CLI passes its requested ID through the native importer."""
    from liblaf.cherries import _cli

    remote, target = _native_archive(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    exit_code = _cli.main(
        [
            "--project-dir",
            str(project),
            "--storage",
            str(target.root),
            "--json",
            "show",
            "selected",
            "--remote",
            remote.remote,
        ]
    )

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["record"]["run_id"] == "selected"
    assert len(result["projection"]["notes"]) == 128
    assert target.list_records() == ["selected"]
    assert len(list((target.root / "metadata" / "events").glob("*/*.json"))) == 129
    assert not list((target.root / "objects" / "sha256").glob("*/*"))


def _event_batch(tmp_path: Path) -> tuple[Store, list[tuple[Path, bytes]]]:
    remote, target = _native_archive(tmp_path)
    assert remote.local is not None
    files = [
        (path.relative_to(remote.local), path.read_bytes())
        for path in sorted((remote.local / "metadata" / "events").glob("*/*.json"))
    ][:3]
    return target, files


@pytest.mark.parametrize("failure_number", [1, 2])
def test_batch_file_fsync_failure_preserves_partial_bytes_and_retry_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_number: int
) -> None:
    """A failed file flush is never reported as a complete successful batch."""
    target, files = _event_batch(tmp_path)
    calls = 0
    original_fsync = os.fsync

    def fail_file_fsync(fd: int) -> None:
        nonlocal calls
        if stat.S_ISREG(os.fstat(fd).st_mode):
            calls += 1
            if calls == failure_number:
                raise OSError(errno.EIO, "injected file fsync failure")
        original_fsync(fd)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", fail_file_fsync)
        with pytest.raises(OSError, match="injected file fsync"):
            target.import_metadata_files(files)

    installed = [path for path, _data in files if (target.root / path).exists()]
    assert len(installed) == failure_number - 1
    for path, data in files:
        if (target.root / path).exists():
            assert (target.root / path).read_bytes() == data
    fresh = Store(target.root)
    fresh.ensure_initialized("collection")
    assert fresh.import_metadata_files(files) == len(files) - len(installed)
    assert all((target.root / path).read_bytes() == data for path, data in files)
    assert not list((target.root / "metadata" / "events").glob("*/.*"))


def test_batch_directory_fsync_failure_requires_verified_fresh_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Visible names from a failed batch must be fenced on an identical retry."""
    target, files = _event_batch(tmp_path)
    leaf = target.root / files[0][0].parent
    original_sync = target._fsync_dir  # noqa: SLF001
    attempted: list[Path] = []

    def fail_leaf(path: Path) -> None:
        attempted.append(path)
        if path == leaf:
            raise OSError(errno.EIO, "injected directory fsync failure")
        original_sync(path)

    with monkeypatch.context() as scoped:
        scoped.setattr(target, "_fsync_dir", fail_leaf)
        with pytest.raises(OSError, match="injected directory fsync"):
            target.import_metadata_files(files)

    assert all((target.root / path).read_bytes() == data for path, data in files)
    assert target.root in attempted
    fresh = Store(target.root)
    fresh.ensure_initialized("collection")
    retried: list[Path] = []

    def track_sync(path: Path) -> None:
        retried.append(path)
        original_sync(path)

    monkeypatch.setattr(fresh, "_fsync_dir", track_sync)
    assert fresh.import_metadata_files(files) == 0
    assert retried == [leaf, leaf.parent, leaf.parent.parent, target.root]


@pytest.mark.parametrize("existing", [False, True])
def test_batch_conflict_is_rejected_before_any_new_event_is_installed(
    tmp_path: Path, *, existing: bool
) -> None:
    """One conflicting immutable name cannot partially install its batch peers."""
    target, files = _event_batch(tmp_path)
    conflicting_path, original = files[-1]
    if existing:
        target.import_metadata_files([(conflicting_path, original)])
    batch = [*files, (conflicting_path, original + b" ")]
    before = {
        path.relative_to(target.root): path.read_bytes()
        for path in (target.root / "metadata").rglob("*")
        if path.is_file()
    }

    with pytest.raises(StoreIntegrityError, match="conflict"):
        target.import_metadata_files(batch)

    after = {
        path.relative_to(target.root): path.read_bytes()
        for path in (target.root / "metadata").rglob("*")
        if path.is_file()
    }
    assert after == before


def test_two_machine_batch_fences_shared_namespace_once_and_deduplicates_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, files = _event_batch(tmp_path)
    relative, data = files[0]
    other_event = json.loads(data)
    other_event["machine_id"] = "other-machine"
    other_path = relative.parent.parent / "other-machine" / relative.name
    other_data = canonical_json(other_event)
    synced: list[Path] = []
    original_sync = target._fsync_dir  # noqa: SLF001

    def track_sync(path: Path) -> None:
        synced.append(path)
        original_sync(path)

    monkeypatch.setattr(target, "_fsync_dir", track_sync)
    assert (
        target.import_metadata_files(
            [(relative, data), (other_path, other_data), (relative, data)]
        )
        == 2
    )
    assert set(synced) == {
        target.root / relative.parent,
        target.root / other_path.parent,
        target.root / "metadata" / "events",
        target.root / "metadata",
        target.root,
    }
    assert len(synced) == 5
    assert (target.root / relative).read_bytes() == data
    assert (target.root / other_path).read_bytes() == other_data


def test_process_kill_after_first_event_publication_allows_verified_retry(
    tmp_path: Path,
) -> None:
    """An actual process kill tests partial import recovery, not power-loss safety."""
    import signal
    import subprocess
    import sys

    remote, target = _native_archive(tmp_path)
    old_work = target.start_work("historical-failed")
    (old_work / "evidence.txt").write_text("retain historical work")
    before = {
        path.relative_to(target.root): path.read_bytes()
        for area in ("work", "pending")
        for path in (target.root / area).rglob("*")
        if path.is_file()
    }
    script = """
import os
from pathlib import Path
import signal
import sys
from liblaf.cherries._remote import Remote
from liblaf.cherries.records import Store
store = Store(Path(sys.argv[1]))
original = store._atomic_bytes
def crash(path, data, **kwargs):
    original(path, data, **kwargs)
    if path.relative_to(store.root).parts[:2] == ('metadata', 'events'):
        os.kill(os.getpid(), signal.SIGKILL)
store._atomic_bytes = crash
Remote(Path(sys.argv[2])).import_metadata(store, 'selected')
raise AssertionError('killed importer must never return success')
"""
    child = subprocess.run(
        [sys.executable, "-I", "-c", script, str(target.root), remote.remote],
        check=False,
        capture_output=True,
        timeout=15,
    )

    assert child.returncode == -signal.SIGKILL, child.stderr.decode()
    assert len(list((target.root / "metadata" / "events").glob("*/*.json"))) == 1
    fresh = Store(target.root)
    assert remote.import_metadata(fresh, "selected") == {"records": 0, "events": 128}
    assert len(fresh.projection("selected")["notes"]) == 128
    assert fresh.projection("selected")["holds"] == set()
    after = {
        path.relative_to(target.root): path.read_bytes()
        for area in ("work", "pending")
        for path in (target.root / area).rglob("*")
        if path.is_file()
    }
    assert after == before

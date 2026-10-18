# Copyright (c) 2026 liblaf
# ruff: noqa: SLF001
"""A published seal stays authoritative when disposable cleanup fails."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from liblaf import cherries
from liblaf.cherries.records import Store, _store

_SCRIPT = """\
from liblaf import cherries

class Config(cherries.BaseConfig):
    readonly: bool = False

def main(cfg: Config):
    scratch = cherries.temp("copied")
    scratch.mkdir()
    nested = scratch / "nested"
    nested.mkdir()
    (nested / "tiny.txt").write_text("scratch\\n")
    cherries.output("result.txt").write_text("retained result\\n")
    if cfg.readonly:
        (nested / "tiny.txt").chmod(0o444)
        nested.chmod(0o555)
    print("MAIN_COMPLETED", flush=True)

if __name__ == "__main__":
    cherries.main(main)
"""


def _events(store: Store, run_id: str) -> list[dict[str, Any]]:
    return [
        value
        for path in (store.root / "metadata" / "events").glob("*/*.json")
        if (value := json.loads(path.read_text()))["subject"] == run_id
    ]


def _work(store: Store, run_id: str = "run") -> Path:
    work = store.start_work(run_id)
    output = work / "outputs" / "result.txt"
    output.parent.mkdir()
    output.write_text("retained result\n")
    return work


def _assert_readable(store: Store, run_id: str, root_digest: str) -> None:
    complete = json.loads(
        (store.root / "records" / run_id / "complete.json").read_text()
    )
    assert complete["root_digest"] == root_digest
    with cherries.open_run(run_id, store=store) as reader:
        assert reader.path("outputs/result.txt").read_text() == "retained result\n"
    assert reader.closed is True


def _control_hashes(store: Store, run_id: str) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (store.root / "records" / run_id).iterdir()
    }


@pytest.mark.skipif(os.getuid() == 0, reason="requires ordinary permission checks")
@pytest.mark.parametrize("readonly", [False, True])
def test_normal_main_preserves_committed_outcome_with_readonly_scratch(
    tmp_path: Path, *, readonly: bool
) -> None:
    script = tmp_path / "experiment.py"
    script.write_text(_SCRIPT)
    root = tmp_path / "store"
    environment = os.environ.copy()
    environment.pop("CHERRIES_PARENT_RUN", None)
    environment["CHERRIES_STORAGE"] = str(root)
    environment["CHERRIES_COMET"] = "0"
    process = subprocess.run(
        [sys.executable, str(script), "--readonly", str(readonly).lower()],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    assert "MAIN_COMPLETED" in process.stdout
    assert "Saved Cherries run" in process.stderr
    store = Store(root)
    [run_id] = store.list_records()
    events = _events(store, run_id)
    assert [event["kind"] for event in events] == ["sealed"]
    assert not (root / "pending" / f"{run_id}.json").exists()
    if readonly:
        assert "work_cleanup" in process.stderr
        assert (
            root / "work" / run_id / "scratch/copied/nested/tiny.txt"
        ).read_text() == "scratch\n"
    else:
        assert not (root / "work" / run_id / "scratch").exists()
        assert not (root / "work" / run_id / ".cherries-work.json").exists()
    assert store.read_record(run_id)["record"]["execution"]["exit_code"] == 0
    _assert_readable(store, run_id, events[0]["value"]["root_digest"])
    # pytest's temporary-directory cleanup must not trip over our test-owned mode.
    if readonly:
        (root / "work" / run_id / "scratch/copied/nested").chmod(0o755)


@pytest.mark.parametrize("stage", ["sealed_event", "pending_cleanup", "work_cleanup"])
def test_postcommit_io_failures_return_committed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    store = Store(tmp_path / "store")
    work = _work(store)
    pending = store.root / "pending/run.json"
    original_event = store.append_event
    original_unlink = Path.unlink
    original_rmtree = _store.shutil.rmtree

    def event(kind: str, *args: Any, **kwargs: Any) -> Any:
        if stage == "sealed_event" and kind == "sealed":
            raise OSError(errno.ENOSPC, "event publication full")
        return original_event(kind, *args, **kwargs)

    def unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if stage == "pending_cleanup" and path == pending:
            assert (
                sum(value["kind"] == "sealed" for value in _events(store, "run")) == 1
            )
            raise OSError(errno.EIO, "pending cleanup failed")
        original_unlink(path, *args, **kwargs)

    def rmtree(path: Path, *args: Any, **kwargs: Any) -> None:
        if stage == "work_cleanup" and Path(path) == work:
            assert (
                sum(value["kind"] == "sealed" for value in _events(store, "run")) == 1
            )
            raise OSError(errno.EIO, "work cleanup failed")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store, "append_event", event)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(_store.shutil, "rmtree", rmtree)
    result = store.seal("run", {}, work)
    assert result["committed"] is True
    assert [warning["stage"] for warning in result["warnings"]] == [stage]
    assert result["warnings"][0]["errno"] == (
        errno.ENOSPC if stage == "sealed_event" else errno.EIO
    )
    assert result["warnings"][0]["path"]
    assert result["warnings"][0]["error"]
    assert work.is_dir()
    assert (work / "outputs/result.txt").read_text() == "retained result\n"
    assert pending.exists() is (stage != "work_cleanup")
    events = _events(store, "run")
    assert [value["kind"] for value in events] == (
        [] if stage == "sealed_event" else ["sealed"]
    )
    if events:
        assert events[0]["value"]["root_digest"] == result["root_digest"]
    controls = _control_hashes(store, "run")
    _assert_readable(store, "run", result["root_digest"])
    assert _control_hashes(store, "run") == controls


def test_precommit_failure_remains_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "store")
    work = _work(store)

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.EIO, "payload publication failed")

    monkeypatch.setattr(store, "_put_object", fail)
    with pytest.raises(OSError, match="payload publication failed"):
        store.seal("run", {}, work)
    assert store.list_records() == []
    assert (store.root / "pending/run.json").is_file()
    assert (work / "outputs/result.txt").read_text() == "retained result\n"
    assert _events(store, "run") == []


def test_postrename_fsync_failure_exposes_unconfirmed_durability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from liblaf.cherries.records import PublishedSealError

    store = Store(tmp_path / "store")
    work = _work(store)
    original_fsync = store._fsync_dir

    def fsync(path: Path) -> None:
        if path == store.root / "records":
            raise OSError(errno.EIO, "record directory fsync failed")
        original_fsync(path)

    monkeypatch.setattr(store, "_fsync_dir", fsync)
    with pytest.raises(PublishedSealError) as caught:
        store.seal("run", {}, work)
    result = caught.value.result
    assert result["published"] is True
    assert result.get("committed") is not True
    assert result["durability"] == "unconfirmed"
    assert [warning["stage"] for warning in result["warnings"]] == ["record_durability"]
    assert (store.root / "pending/run.json").is_file()
    assert work.is_dir()
    assert _events(store, "run") == []
    _assert_readable(store, "run", result["root_digest"])


def test_recovery_cleanup_failure_does_not_block_verified_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "store")
    work = _work(store)
    original_rmtree = _store.shutil.rmtree

    def fail_work(path: Path, *args: Any, **kwargs: Any) -> None:
        if Path(path) == work:
            raise OSError(errno.EIO, "persistent cleanup failure")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(_store.shutil, "rmtree", fail_work)
    result = store.seal("run", {}, work)
    assert result["committed"] is True
    controls = _control_hashes(store, "run")
    fresh = Store(store.root)
    fresh.ensure_initialized()
    assert fresh.list_records() == ["run"]
    assert work.is_dir()
    _assert_readable(fresh, "run", result["root_digest"])
    assert _control_hashes(fresh, "run") == controls


@pytest.mark.parametrize("stage", ["work_cleanup", "record_durability", "precommit"])
def test_main_reports_real_process_outcome_at_commit_boundary(
    tmp_path: Path, stage: str
) -> None:
    script = tmp_path / "experiment.py"
    injection = f"""\
import errno
from pathlib import Path
from liblaf.cherries.records import Store
from liblaf.cherries.records import _store
stage = {stage!r}
_original_rmtree = _store.shutil.rmtree
_original_fsync = Store._fsync_dir
_original_put = Store._put_object

def _rmtree(path, *args, **kwargs):
    if stage == "work_cleanup" and Path(path).parent.name == "work":
        raise OSError(errno.EIO, "injected work cleanup failure")
    return _original_rmtree(path, *args, **kwargs)

def _fsync(path):
    if stage == "record_durability" and path.name == "records":
        raise OSError(errno.EIO, "injected record fsync failure")
    return _original_fsync(path)

def _put(self, *args, **kwargs):
    if stage == "precommit":
        raise OSError(errno.EIO, "injected payload failure")
    return _original_put(self, *args, **kwargs)

_store.shutil.rmtree = _rmtree
Store._fsync_dir = staticmethod(_fsync)
Store._put_object = _put
"""
    script.write_text(injection + _SCRIPT)
    root = tmp_path / "store"
    environment = os.environ.copy()
    environment.pop("CHERRIES_PARENT_RUN", None)
    environment["CHERRIES_STORAGE"] = str(root)
    environment["CHERRIES_COMET"] = "0"
    process = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert "MAIN_COMPLETED" in process.stdout
    store = Store(root)
    events = [
        json.loads(path.read_text())
        for path in (root / "metadata/events").glob("*/*.json")
    ]
    kinds = [event["kind"] for event in events]
    if stage == "work_cleanup":
        assert process.returncode == 0, process.stderr
        assert "Saved Cherries run" in process.stderr
        assert "work_cleanup" in process.stderr
        assert kinds == ["sealed"]
    else:
        assert process.returncode != 0
        assert "Saved Cherries run" not in process.stderr
        if stage == "precommit":
            assert store.list_records() == []
            assert kinds == ["recording-incomplete"]
            assert len(list((root / "pending").glob("*.json"))) == 1
            return
        assert "durability" in process.stderr
        assert "unconfirmed" in process.stderr
        assert "recording-incomplete" not in kinds
    [run_id] = store.list_records()
    complete = json.loads((root / "records" / run_id / "complete.json").read_text())
    _assert_readable(store, run_id, complete["root_digest"])


@pytest.mark.parametrize("failure", ["logging", "durability"])
def test_run_retains_published_result_without_claiming_recording_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from liblaf.cherries.core import Run, _run
    from liblaf.cherries.records import PublishedSealError

    script = tmp_path / "experiment.py"
    script.write_text("from liblaf import cherries\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(script)])
    monkeypatch.delenv("CHERRIES_PARENT_RUN", raising=False)
    run = Run(store_root=tmp_path / "store")
    run.repo = None
    run.start()
    run.output("result.txt").write_text("retained result\n")
    store = run.store
    assert store is not None
    original_info = _run.logger.info
    original_fsync = store._fsync_dir

    def info(message: str, *args: Any, **kwargs: Any) -> None:
        if message == "Saved Cherries run %s":
            raise OSError(errno.ENOSPC, "postcommit log full")
        original_info(message, *args, **kwargs)

    def fsync(path: Path) -> None:
        if path == store.root / "records":
            raise OSError(errno.EIO, "postrename fsync failed")
        original_fsync(path)

    if failure == "logging":
        monkeypatch.setattr(_run.logger, "info", info)
        run.end()
    else:
        monkeypatch.setattr(store, "_fsync_dir", fsync)
        with pytest.raises(PublishedSealError):
            run.end()
    assert run.active is False
    result = run.record_result
    assert result is not None
    assert result["run_id"] == run.run_id
    kinds = [event["kind"] for event in _events(store, run.run_id)]
    assert "recording-incomplete" not in kinds
    if failure == "logging":
        assert result["committed"] is True
        assert kinds == ["sealed"]
    else:
        assert result.get("committed") is not True
        assert result["published"] is True
        assert result["durability"] == "unconfirmed"
        assert (store.root / "pending" / f"{run.run_id}.json").is_file()
        assert (
            run.working_dir / "outputs/result.txt"
        ).read_text() == "retained result\n"
    _assert_readable(store, run.run_id, result["root_digest"])


def test_directory_fsync_failure_closes_its_real_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[int] = []

    def fsync(descriptor: int) -> None:
        assert stat.S_ISDIR(os.fstat(descriptor).st_mode)
        opened.append(descriptor)
        raise OSError(errno.EIO, "injected directory fsync failure")

    monkeypatch.setattr(_store.os, "fsync", fsync)
    try:
        with pytest.raises(OSError, match="injected directory fsync failure"):
            Store._fsync_dir(tmp_path)
        [descriptor] = opened
        with pytest.raises(OSError, match="Bad file descriptor") as caught:
            os.fstat(descriptor)
        assert caught.value.errno == errno.EBADF
    finally:
        # Also release a descriptor if this regression is run against old code.
        for descriptor in opened:
            with suppress(OSError):
                os.close(descriptor)

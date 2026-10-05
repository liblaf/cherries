# Copyright (c) 2026 liblaf
"""Run sealing behavior around threads created during an experiment."""

from __future__ import annotations

import _thread
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from liblaf.cherries.core import Run
from liblaf.cherries.core import _run as run_module


class _FixedIdentThread(threading.Thread):
    """Real managed thread with a deterministic reusable thread identifier."""

    @property
    def ident(self) -> int:
        return 1


def _started_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Run:
    monkeypatch.chdir(tmp_path)
    entrypoint = tmp_path / "experiment.py"
    entrypoint.write_text("from liblaf import cherries\n")
    monkeypatch.setattr(sys, "argv", [str(entrypoint)])
    run = Run(store_root=tmp_path / "store")
    run.repo = None
    run.start()
    return run


def test_alien_thread_bookkeeping_does_not_block_normal_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A low-level thread can register a non-joinable bookkeeping thread."""
    run = _started_run(tmp_path, monkeypatch)
    registered = threading.Event()
    release = threading.Event()
    done = threading.Event()

    def alien() -> None:
        threading.current_thread()
        registered.set()
        release.wait()
        done.set()

    _thread.start_new_thread(alien, ())
    try:
        assert registered.wait(timeout=1)
        run.output("result.txt").write_text("sealed\n")
        run.end()
    finally:
        release.set()
        assert done.wait(timeout=1)

    assert run.store is not None
    assert (
        run.store.materialize(run.run_id, "outputs/result.txt").read_text()
        == "sealed\n"
    )


@pytest.mark.parametrize("daemon", [False, True])
def test_active_managed_thread_retains_work_until_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, daemon: bool
) -> None:
    run = _started_run(tmp_path, monkeypatch)
    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=daemon)
    worker.start()
    monotonic: Callable[[], float] = run_module.time.monotonic
    ticks = iter((0.0, 5.0))
    monkeypatch.setattr(run_module.time, "monotonic", lambda: next(ticks))

    try:
        with pytest.raises(RuntimeError, match="thread is still running"):
            run.end()
        assert run.store is not None
        assert run.store.list_records() == []
    finally:
        release.set()
        worker.join(timeout=1)
        monkeypatch.setattr(run_module.time, "monotonic", monotonic)

    assert not worker.is_alive()
    assert run.store is not None
    assert run.store.list_records() == []
    assert (run.store.root / "work" / run.run_id).is_dir()


def test_new_managed_thread_with_reused_identifier_still_blocks_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_release = threading.Event()
    baseline = _FixedIdentThread(target=baseline_release.wait)
    baseline.start()
    try:
        run = _started_run(tmp_path, monkeypatch)
        baseline_release.set()
        baseline.join(timeout=1)
        assert not baseline.is_alive()

        release = threading.Event()
        worker = _FixedIdentThread(target=release.wait)
        worker.start()
        monotonic: Callable[[], float] = run_module.time.monotonic
        ticks = iter((0.0, 5.0))
        monkeypatch.setattr(run_module.time, "monotonic", lambda: next(ticks))
        try:
            with pytest.raises(RuntimeError, match="thread is still running"):
                run.end()
            assert run.store is not None
            assert run.store.list_records() == []
        finally:
            release.set()
            worker.join(timeout=1)
            monkeypatch.setattr(run_module.time, "monotonic", monotonic)

        assert not worker.is_alive()
    finally:
        baseline_release.set()
        baseline.join(timeout=1)


def test_completed_managed_thread_is_joined_before_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _started_run(tmp_path, monkeypatch)
    release = threading.Event()
    worker = threading.Thread(target=release.wait)
    worker.start()
    join = worker.join
    calls: list[float | None] = []

    def release_and_join(timeout: float | None = None) -> None:
        calls.append(timeout)
        release.set()
        join(timeout)

    monkeypatch.setattr(worker, "join", release_and_join)
    try:
        run.end()
    finally:
        release.set()
        join(timeout=1)

    assert calls
    assert not worker.is_alive()
    assert run.store is not None
    assert run.store.list_records() == [run.run_id]

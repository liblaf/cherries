# Copyright (c) 2026 liblaf
"""Process sealing contracts, exercised in fresh interpreters."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from multiprocessing import resource_tracker
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from liblaf.cherries.core import Run
from liblaf.cherries.records import Store

_EXPERIMENT = """\
import json
import multiprocessing as mp
from multiprocessing import resource_tracker
import os
from pathlib import Path
import subprocess
import sys
import time

from liblaf.cherries.core import Run


def worker(wait=False):
    if wait:
        time.sleep(60)
    assert sum(range(10)) == 45


def experiment():
    scenario = sys.argv[1]
    run = Run(store_root=Path("store").resolve())
    run.repo = None
    run.start()
    result = run.output("result.txt")
    result.write_text("completed\\n")
    process = None
    tracker_pid = None
    worker_exitcode = None
    saved_stderr = None
    original_tracker = None
    unrelated_pipe = None
    try:
        if scenario in {"joined", "tracker-writer", "spawn-live"}:
            if scenario == "tracker-writer":
                saved_stderr = os.dup(2)
                with (run.working_dir / "tracker-stderr.txt").open("w") as handle:
                    os.dup2(handle.fileno(), 2)
            process = mp.get_context("spawn").Process(target=worker, args=(scenario == "spawn-live",))
            process.start()
            tracker_pid = resource_tracker._resource_tracker._pid
            if scenario != "spawn-live":
                process.join(timeout=20)
                worker_exitcode = process.exitcode
                assert worker_exitcode == 0
                process.close()
                process = None
            if saved_stderr is not None:
                os.dup2(saved_stderr, 2)
                os.close(saved_stderr)
                saved_stderr = None
        else:
            # Read stdin so the child remains alive until explicit cleanup.
            command = [sys.executable, "-c", "import sys; sys.stdin.read()"]
            if scenario in {"spoofed", "forged-pipe", "forged-no-fd"}:
                command.append("from multiprocessing.resource_tracker import main;main(0)")
            process = subprocess.Popen(command, stdin=subprocess.PIPE)
            if scenario in {"forged-pipe", "forged-no-fd"}:
                tracker = resource_tracker._resource_tracker
                original_tracker = (tracker._pid, tracker._fd)
                tracker._pid = process.pid
                if scenario == "forged-pipe":
                    # A stale singleton PID must not identify another child
                    # that has no read end of the parent's tracker pipe.
                    unrelated_pipe = os.pipe()
                    tracker._fd = unrelated_pipe[1]
                else:
                    tracker._fd = None
        tracker_alive = tracker_pid is not None and Path(f"/proc/{tracker_pid}").exists()
        error = None
        try:
            run.end()
        except RuntimeError as exc:
            error = str(exc)
        Path("report.json").write_text(json.dumps({
            "run_id": run.run_id,
            "error": error,
            "tracker_alive": tracker_alive,
            "worker_exitcode": worker_exitcode,
        }))
    finally:
        if original_tracker is not None:
            tracker = resource_tracker._resource_tracker
            tracker._pid, tracker._fd = original_tracker
        if unrelated_pipe is not None:
            for descriptor in unrelated_pipe:
                os.close(descriptor)
        if saved_stderr is not None:
            os.dup2(saved_stderr, 2)
            os.close(saved_stderr)
        if process is not None:
            if isinstance(process, subprocess.Popen):
                process.communicate(timeout=20)
            else:
                process.terminate()
                process.join(timeout=20)
                process.close()
        resource_tracker._resource_tracker._stop()


if __name__ == "__main__":
    experiment()
"""


def _run_case(tmp_path: Path, scenario: str) -> tuple[Store, dict[str, Any]]:
    script = tmp_path / "experiment.py"
    script.write_text(_EXPERIMENT)
    environment = os.environ.copy()
    environment.pop("CHERRIES_PARENT_RUN", None)
    subprocess.run(
        [sys.executable, str(script), scenario],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        timeout=60,
    )
    return Store(tmp_path / "store"), json.loads((tmp_path / "report.json").read_text())


@pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="Linux process guards")
def test_joined_spawn_worker_seals_with_live_resource_tracker(tmp_path: Path) -> None:
    store, report = _run_case(tmp_path, "joined")
    assert report["worker_exitcode"] == 0
    assert report["tracker_alive"] is True
    assert report["error"] is None
    assert store.list_records() == [report["run_id"]]
    assert (
        store.materialize(report["run_id"], "outputs/result.txt").read_text()
        == "completed\n"
    )


@pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="Linux process guards")
@pytest.mark.parametrize(
    "scenario",
    [
        "ordinary",
        "spawn-live",
        "spoofed",
        "forged-pipe",
        "forged-no-fd",
        "tracker-writer",
    ],
)
def test_live_processes_retain_work_including_tracker_with_writable_file(
    tmp_path: Path, scenario: str
) -> None:
    store, report = _run_case(tmp_path, scenario)
    assert report["error"] is not None
    if scenario == "tracker-writer":
        assert report["tracker_alive"] is True
        assert report["worker_exitcode"] == 0
        assert "writable work files" in report["error"]
    else:
        assert "child process is still running" in report["error"]
    assert store.list_records() == []
    assert (store.root / "pending" / f"{report['run_id']}.json").is_file()
    work = store.root / "work" / report["run_id"]
    assert (work / "outputs" / "result.txt").read_text() == "completed\n"
    assert not (store.root / "records" / report["run_id"] / "complete.json").exists()


@pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="Linux process guards")
def test_tracker_identity_inspection_does_not_manage_helper_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inspect a test-owned tracker without starting, probing or stopping it."""
    tracker = resource_tracker.ResourceTracker()
    tracker.ensure_running()
    pid = tracker._pid  # noqa: SLF001

    def unexpected_lifecycle_call(*_args: object, **_kwargs: object) -> None:
        pytest.fail("identity inspection must not manage tracker lifecycle")

    try:
        with monkeypatch.context() as patches:
            patches.setattr(resource_tracker, "_resource_tracker", tracker)
            for name in ("ensure_running", "getfd", "_check_alive", "_stop"):
                patches.setattr(tracker, name, unexpected_lifecycle_call)
            assert Run._is_resource_tracker(pid) is True  # noqa: SLF001
            assert Run._is_resource_tracker(os.getpid()) is False  # noqa: SLF001
    finally:
        tracker._stop()  # noqa: SLF001


@pytest.mark.skipif(not Path("/proc/self/fd").exists(), reason="Linux process guards")
@pytest.mark.parametrize("proof", ["regular-file", "read-pipe", "closed-pipe"])
def test_tracker_identity_requires_an_open_write_fifo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, proof: str
) -> None:
    """A matching PID alone cannot replace the parent write-pipe proof."""
    read_fd, write_fd = os.pipe()
    try:
        with (tmp_path / "regular.txt").open("w") as regular:
            descriptor = {
                "regular-file": regular.fileno(),
                "read-pipe": read_fd,
                "closed-pipe": write_fd,
            }[proof]
            if proof == "closed-pipe":
                os.close(write_fd)
                write_fd = None
            tracker = SimpleNamespace(_pid=os.getpid(), _fd=descriptor)
            monkeypatch.setattr(resource_tracker, "_resource_tracker", tracker)
            assert Run._is_resource_tracker(os.getpid()) is False  # noqa: SLF001
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


@pytest.mark.parametrize(
    "tracker",
    [
        None,
        SimpleNamespace(),
        SimpleNamespace(_pid=1),
        SimpleNamespace(_pid=1, _fd=True),
    ],
)
def test_tracker_identity_fails_closed_when_private_state_is_missing(
    monkeypatch: pytest.MonkeyPatch, tracker: object
) -> None:
    monkeypatch.setattr(resource_tracker, "_resource_tracker", tracker)
    assert Run._is_resource_tracker(1) is False  # noqa: SLF001

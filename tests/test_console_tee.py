# Copyright (c) 2026 liblaf
from __future__ import annotations

import errno
import io
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

import pytest

from liblaf.cherries._main._main import _Tee
from liblaf.cherries.records import Store


class FailingStream(io.StringIO):
    def __init__(self, operation: str, error: Exception) -> None:
        super().__init__()
        self.operation = operation
        self.error = error
        self.calls: list[str] = []

    def write(self, text: str) -> int:
        self.calls.append("write")
        if self.operation == "write":
            raise self.error
        return super().write(text)

    def flush(self) -> None:
        self.calls.append("flush")
        if self.operation == "flush":
            raise self.error
        super().flush()


@pytest.mark.parametrize("operation", ["write", "flush"])
def test_broken_console_preserves_log_and_disables_further_console_calls(
    operation: str,
) -> None:
    console = FailingStream(operation, BrokenPipeError(errno.EPIPE, "closed reader"))
    log = FailingStream("", RuntimeError("unused"))
    tee = _Tee(console, log)

    assert tee.write("before\n") == len("before\n")
    tee.flush()
    calls_after_disconnect = console.calls.copy()
    assert tee.write("after\n") == len("after\n")
    tee.flush()

    assert log.getvalue() == "before\nafter\n"
    assert console.calls == calls_after_disconnect
    assert log.calls == ["write", "flush", "write", "flush"]
    assert calls_after_disconnect.count(operation) == 1


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENOSPC, "durable log full"),
        BrokenPipeError(errno.EPIPE, "durable log pipe closed"),
    ],
)
def test_durable_log_errors_propagate(operation: str, error: OSError) -> None:
    tee = _Tee(io.StringIO(), FailingStream(operation, error))

    invoke = (lambda: tee.write("payload")) if operation == "write" else tee.flush
    with pytest.raises(OSError, match="durable log") as caught:
        invoke()

    assert caught.value is error


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize(
    "error", [ValueError("closed console"), OSError(errno.EIO, "console I/O failure")]
)
def test_unrelated_console_errors_propagate(operation: str, error: Exception) -> None:
    tee = _Tee(FailingStream(operation, error), io.StringIO())

    invoke = (lambda: tee.write("payload")) if operation == "write" else tee.flush
    with pytest.raises(type(error), match="console") as caught:
        invoke()

    assert caught.value is error


@pytest.mark.parametrize("console", ["stdout", "stderr", "shared"])
@pytest.mark.parametrize("explicit_flush", [True, False])
def test_closed_pipe_reader_does_not_fail_or_discard_experiment(
    tmp_path: Path,
    console: Literal["stdout", "stderr", "shared"],
    *,
    explicit_flush: bool,
) -> None:
    target = "stderr" if console == "stderr" else "stdout"
    script = tmp_path / "experiment.py"
    after_disconnect = (
        "    print('durable after disconnect', file=stream)\n"
        "    stream.flush()\n"
        "    print('durable subsequent message', file=stream, flush=True)\n"
        "    print('other console message', file=sys.stderr if stream is sys.stdout else sys.stdout, flush=True)\n"
        if explicit_flush
        else "    stream.write('durable final message')\n"
    )
    after_main = (
        ""
        if console == "shared"
        else f"print('healthy console after capture', file=sys.{'stdout' if target == 'stderr' else 'stderr'}, flush=True)\n"
    )
    script.write_text(
        "import sys\n"
        "from liblaf import cherries\n"
        "def experiment():\n"
        f"    stream = sys.{target}\n"
        "    print('READY', file=stream, flush=True)\n"
        "    assert sys.stdin.readline() == 'continue\\n'\n"
        f"{after_disconnect}"
        "    cherries.output('result.txt').write_text('completed')\n"
        "cherries.main(experiment)\n"
        f"{after_main}"
    )
    store = Store(tmp_path / "store")
    diagnostics = tmp_path / "console.txt"
    with diagnostics.open("w") as other_console:
        process = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=tmp_path,
            env={
                "PATH": os.environ["PATH"],
                "HOME": os.environ["HOME"],
                "CHERRIES_STORAGE": str(store.root),
                "CHERRIES_COMET": "0",
            },
            stdin=subprocess.PIPE,
            stdout=other_console if console == "stderr" else subprocess.PIPE,
            stderr=(
                subprocess.STDOUT
                if console == "shared"
                else subprocess.PIPE
                if console == "stderr"
                else other_console
            ),
        )
        try:
            reader = process.stderr if console == "stderr" else process.stdout
            assert reader is not None
            received = b""
            deadline = time.monotonic() + 30
            while b"READY\n" not in received:
                ready, _, _ = select.select(
                    [reader], [], [], max(0, deadline - time.monotonic())
                )
                assert ready, f"experiment did not announce readiness: {received!r}"
                chunk = os.read(reader.fileno(), 4096)
                assert chunk, f"experiment exited before readiness: {received!r}"
                received += chunk
            reader.close()
            if console == "stderr":
                process.stderr = None
            else:
                process.stdout = None
            process.communicate(b"continue\n", timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    assert process.returncode == 0, diagnostics.read_text()
    if console != "shared":
        assert "healthy console after capture\n" in diagnostics.read_text()
    [run_id] = store.list_records()
    record = store.read_record(run_id)["record"]
    assert record["execution"] == {"status": "succeeded", "exit_code": 0}
    assert store.materialize(run_id, "outputs/result.txt").read_text() == "completed"
    log = store.materialize(run_id, f"logs/{target}.log").read_text()
    expected_log = (
        "READY\ndurable after disconnect\ndurable subsequent message\n"
        if explicit_flush
        else "READY\ndurable final message"
    )
    assert log == expected_log
    other = "stdout" if target == "stderr" else "stderr"
    expected_other = "other console message\n" if explicit_flush else ""
    assert store.materialize(run_id, f"logs/{other}.log").read_text() == expected_other
    assert not store.list_attempts()

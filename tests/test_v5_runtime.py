# Copyright (c) 2026 liblaf
"""Execution tests cover publication ownership and durable recording failures."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import polars as pl
import pytest

from liblaf.cherries.store import _runtime
from liblaf.cherries.store._io import IntegrityError, StoreError
from liblaf.cherries.store._runtime import (
    MetricsWriter,
    current_run,
    finalize_metrics,
)
from liblaf.cherries.store._store import Project, Store


@pytest.fixture
def project(tmp_path: Path) -> Project:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ("init",),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "core.hooksPath", ".git/hooks"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "main.py").write_text("print('source')\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    store = Store.create(tmp_path / "store", cache_root=tmp_path / "cache")
    return store.projects.add("demo", repo=repo)


def test_context_metric_fsync_order_nonfinite_and_repeated_runs(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = os.fsync
    synced: list[str] = []

    def fsync(descriptor: int) -> None:
        synced.append(str(Path(f"/proc/self/fd/{descriptor}").readlink()))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    with project.run(name="first", parameters={"steps": 2}) as run:
        assert current_run() is run
        run.output("result.txt").write_text("actual output")
        run.log_metrics({"loss": 2.0, "gradient": math.inf}, step=4, timestamp_ms=100)
        assert synced[-1].endswith("metrics.jsonl")
        run.log_metric("loss", 1.0, step=4, timestamp_ms=100)
        run.log_metric("loss", math.nan, step=4, timestamp_ms=100)
        lines = [
            json.loads(line)
            for line in (run.directory / "metrics.jsonl").read_text().splitlines()
        ]
        assert lines[-1]["value"] == "NaN"
        assert lines[1]["value"] == "Infinity"
        assert all(
            set(row) == {"name", "step", "timestamp_ms", "value"} for row in lines
        )
        print("captured stdout")
        print("captured stderr", file=sys.stderr)
        first_id = run.id
    assert current_run() is None
    assert run.result.saved
    saved = project.runs.get(first_id)
    assert saved.metadata["metrics"]["loss"] == {
        "last": "NaN",
        "min": 1.0,
        "max": 2.0,
        "count": 3,
        "nonfinite_count": 1,
    }
    data = pl.read_parquet(saved.directory / "metrics.parquet")
    assert data.columns == ["name", "step", "timestamp_ms", "value"]
    assert data["name"].to_list() == ["loss", "gradient", "loss", "loss"]
    assert "captured stdout" in (saved.directory / "run.log").read_text()
    assert "captured stderr" in (saved.directory / "run.log").read_text()
    with project.run(name="second") as second:
        assert second.id != first_id
    assert second.result.saved
    with pytest.raises(StoreError, match="no active"):
        run.output("after.txt")


def test_failed_context_keeps_diagnostics_and_original_exception(
    project: Project,
) -> None:
    original = ValueError("solver failed")
    with (  # noqa: PT012 - observe the full context teardown.
        pytest.raises(ValueError, match="solver failed") as caught,
        project.run(name="failed") as run,
    ):
        run.output("not-produced.txt")
        run.log_metric("loss", 3.0)
        raise original
    assert caught.value is original
    assert original.run_result.saved
    saved = project.runs.get(run.id)
    assert saved.metadata["status"] == "failed"
    assert saved.metadata["execution"]["exit_code"] == 1
    assert saved.metadata["missing_outputs"] == ["outputs/not-produced.txt"]
    assert "ValueError: solver failed" in (saved.directory / "run.log").read_text()
    assert saved.metadata["git"]["source_stable"] is True


def test_mutated_consumed_input_prevents_publication_and_preserves_working_bytes(
    project: Project, tmp_path: Path
) -> None:
    source = tmp_path / "input.bin"
    source.write_bytes(b"consumed input")
    with (  # noqa: PT012 - mutated bytes must be checked during teardown.
        pytest.raises(IntegrityError, match="consumed input") as caught,
        project.run(name="mutation") as run,
    ):
        bound = run.input(source)
        binding = run.draft.metadata["input_bindings"][0]
        assert binding["consumed"]
        assert binding["oid"].startswith("sha256:")
        bound.write_bytes(b"incorrect mutation")
        run.log_metric("one", 1.0)
    assert not caught.value.result.saved
    assert run.directory.name.endswith(".tmp")
    assert bound.read_bytes() == b"incorrect mutation"
    assert (run.directory / "metrics.jsonl").exists()
    assert run.draft.metadata["git"]["commit"]


def test_source_boundary_observes_changes_during_execution(project: Project) -> None:
    with project.run(name="changing-source") as run:
        (project.repository / "main.py").write_text(
            "print('changed during execution')\n"
        )
    git = project.runs.get(run.id).metadata["git"]
    assert git["start_fingerprint"] != git["end_fingerprint"]
    assert git["source_stable"] is False
    assert git["replay_verified"] is False


def test_metric_truncation_fails_sealing_without_deleting_source(
    tmp_path: Path,
) -> None:
    writer = MetricsWriter(tmp_path)
    writer.append({"loss": 1.0})
    writer.close()
    with (tmp_path / "metrics.jsonl").open("a") as stream:
        stream.write('{"name":"loss"')
    with pytest.raises(IntegrityError, match="truncated"):
        finalize_metrics(tmp_path)
    assert (tmp_path / "metrics.jsonl").read_text().endswith('{"name":"loss"')
    assert not (tmp_path / "metrics.parquet").exists()


def test_sealing_failure_preserves_original_error_and_execution_result(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_sealing(_directory: Path) -> dict:
        message = "sealing failed"
        raise IntegrityError(message)

    monkeypatch.setattr(_runtime, "finalize_metrics", fail_sealing)
    original = ValueError("solver failed before sealing")
    with (  # noqa: PT012 - the original body exception must survive failed teardown.
        pytest.raises(ValueError, match="solver failed before sealing") as caught,
        project.run(name="failed recording") as run,
    ):
        run.log_metric("loss", 1.0)
        raise original
    assert caught.value is original
    assert isinstance(original.recording_error, IntegrityError)
    assert original.run_result.execution_status == "failed"
    assert original.run_result.saved is False
    assert run.directory.name.endswith(".tmp")
    assert (run.directory / "metrics.jsonl").exists()
    assert run.draft.metadata["status"] == "finalizing"
    assert run.draft.metadata["git"]["commit"]


def test_outer_exec_and_inner_context_publish_once_and_keep_child_metadata(
    project: Project, tmp_path: Path
) -> None:
    script = tmp_path / "child.py"
    script.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "from liblaf.cherries.store._store import Store\n"
        f"store = Store.open(os.environ['CHERRIES_STORE'], cache_root=Path({str(project.store.cache_root)!r}))\n"
        "project = store.projects.get(os.environ['CHERRIES_PROJECT'])\n"
        "with project.run(name='inner', parameters={'n': 2}, tags=['child']) as run:\n"
        "    run.output('result.txt').write_text('child result')\n"
        "    run.log_metric('loss', 0.5, step=2)\n"
        "    run.report().write_text('# Child report\\n')\n"
        "    print('child stdout', flush=True)\n"
        "    assert run.result is None\n"
        "assert run.directory.name.endswith('.tmp')\n"
        "print('after inner context', flush=True)\n"
    )
    draft = project.runs.create(name="outer", kind="visualization", parameters={"n": 2})
    result = draft.execute([sys.executable, str(script)])
    assert result.saved
    assert result.exit_code == 0
    [saved] = list(project.runs)
    assert saved.id == draft.id
    assert saved.metadata["tags"] == ["child"]
    assert saved.metadata["required_outputs"] == ["outputs/result.txt"]
    assert saved.metadata["execution"]["observed_by"] == "cli"
    assert saved.metadata["metrics"]["loss"]["last"] == 0.5
    assert saved.file("outputs/result.txt").materialize().read_text() == "child result"
    log = (saved.directory / "run.log").read_text()
    assert log.count("child stdout") == 1
    assert "after inner context" in log


def test_exec_preserves_native_streams_failure_exit_code_and_launch_diagnostics(
    project: Project,
) -> None:
    failed = project.runs.create(name="native", kind="simulation")
    result = failed.execute(
        [
            sys.executable,
            "-c",
            "import os; os.write(1,b'stdout\\xff\\n'); os.write(2,b'stderr\\n'); raise SystemExit(7)",
        ]
    )
    assert result.saved
    assert result.execution_status == "failed"
    assert result.exit_code == 7
    assert (result.directory / "run.log").read_bytes() == b"stdout\xff\nstderr\n"
    missing = project.runs.create(name="missing command", kind="simulation")
    result = missing.execute(["/a/nonexistent/cherries-test-executable"])
    assert result.saved
    assert result.exit_code == 127
    assert result.execution_status == "failed"
    assert "FileNotFoundError" in (result.directory / "run.log").read_text()

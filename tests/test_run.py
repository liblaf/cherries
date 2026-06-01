from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from liblaf.cherries.core import Run


def make_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str | None = None,
    tags: str | None = None,
) -> tuple[Run, Path]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CHERRIES_NAME", raising=False)
    monkeypatch.delenv("CHERRIES_TAGS", raising=False)
    if name is not None:
        monkeypatch.setenv("CHERRIES_NAME", name)
    if tags is not None:
        monkeypatch.setenv("CHERRIES_TAGS", tags)
    script = tmp_path / "exp" / "2026" / "06" / "01" / "demo" / "src" / "10-main.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("from liblaf import cherries\n")
    monkeypatch.setattr(sys, "argv", [str(script)])

    run = Run()
    run.repo = None
    run.start_time = datetime(2026, 6, 1, 12, 30, 45, tzinfo=UTC)
    return run, script


def test_run_identity_uses_entrypoint_and_optional_custom_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, script = make_run(tmp_path, monkeypatch)

    assert run.entrypoint == script.resolve()
    assert run.working_dir == script.parent.parent
    assert run.run_name == "2026/06/01/demo/10-main"
    assert run.run_key == Path("2026/06/01/demo/10-main/2026-06-01T123045")

    named, _ = make_run(tmp_path, monkeypatch, name="Face Solve 42")

    assert named.run_name == "Face Solve 42"
    assert named.run_key == Path(
        "2026/06/01/demo/10-main/2026-06-01T123045-Face-Solve-42"
    )


def test_run_summary_omits_empty_tags_and_serializes_logged_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _ = make_run(tmp_path, monkeypatch)
    run.log_other("cherries/cmd", "python 10-main.py")
    run.log_other("cherries/entrypoint", Path("exp/2026/06/01/demo/src/10-main.py"))
    run.log_other("cherries/exp_dir", Path("exp/2026/06/01/demo"))
    run.log_other("cherries/start_time", run.start_time)
    run.log_param("optimizer/lr", 0.01)
    output = run.output("metrics.json")
    output.write_text("{}\n")
    run._assets.end()  # noqa: SLF001

    summary = run.summary(prefix=run.working_dir)

    assert "tags" not in summary
    assert summary["name"] == "2026/06/01/demo/10-main"
    assert summary["params"] == {"optimizer": {"lr": 0.01}}
    assert summary["outputs"] == ["data/metrics.json"]
    assert summary["cmd"] == "python 10-main.py"


def test_run_summary_includes_environment_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _ = make_run(tmp_path, monkeypatch, tags="debug,smoke")
    run.log_other("cherries/cmd", "python 10-main.py")

    summary = run.summary()

    assert summary["tags"] == ["debug", "smoke"]

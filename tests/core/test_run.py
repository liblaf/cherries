import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import attrs
import pytest

from liblaf.cherries import core


@attrs.define
class AssetRecorder(core.Plugin):
    calls: list[tuple[Path, dict[str, Any] | None, bool]]

    @core.impl
    def log_asset(
        self,
        path: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        report: bool = True,
    ) -> None:
        self.calls.append(
            (path, dict(metadata) if metadata is not None else None, report)
        )


def make_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    calls: list[tuple[Path, dict[str, Any] | None, bool]],
) -> core.Run:
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "experiment.py")])
    run = core.Run()
    run.project_dir = tmp_path
    run.run_name = "experiment.py"
    run.plugins.register(AssetRecorder(calls))
    return run


def test_path_helpers_log_inputs_and_flush_existing_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[Path, dict[str, Any] | None, bool]] = []
    run = make_run(monkeypatch, tmp_path, calls)
    input_path = tmp_path / "data" / "raw" / "data.csv"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("raw\n")

    assert run.input("raw/data.csv", metadata={"split": "train"}) == input_path
    output = run.output("metrics.json", metadata={"kind": "metrics"})
    temp = run.temp("scratch/state.txt")
    output.write_text("{}\n")
    temp.write_text("state\n")

    run.end()

    assert calls == [
        (input_path, {"type": "input", "split": "train"}, True),
        (output, {"type": "output", "kind": "metrics"}, True),
        (temp, {"type": "temp"}, True),
    ]
    summary = run.summary(prefix=tmp_path)
    assert summary["inputs"] == ["data/raw/data.csv"]
    assert summary["outputs"] == ["data/metrics.json"]
    assert summary["temps"] == ["tmp/scratch/state.txt"]


def test_log_output_expands_series_bundles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[Path, dict[str, Any] | None, bool]] = []
    run = make_run(monkeypatch, tmp_path, calls)
    series = tmp_path / "data" / "mesh.vtp.series"
    frame_dir = series.parent / "mesh.vtp.series.d"
    frame_dir.mkdir(parents=True)
    frames = [
        frame_dir / "mesh_000000.vtp",
        frame_dir / "mesh_000001.vtp",
    ]
    for frame in frames:
        frame.write_text(frame.name)
    series.write_text(
        json.dumps(
            {
                "file-series-version": "1.0",
                "files": [
                    {"name": f"mesh.vtp.series.d/{frame.name}", "time": i}
                    for i, frame in enumerate(frames)
                ],
            }
        )
    )

    run.log_output(series, metadata={"mesh": "face"})

    assert calls == [
        (series, {"type": "output", "mesh": "face"}, True),
        (frames[0], {"type": "output", "mesh": "face"}, False),
        (frames[1], {"type": "output", "mesh": "face"}, False),
    ]
    run.log_other("cherries/start_time", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    assert run.summary(prefix=tmp_path)["outputs"] == ["data/mesh.vtp.series"]


def test_missing_artifact_warns_without_delegating(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, dict[str, Any] | None, bool]] = []
    run = make_run(monkeypatch, tmp_path, calls)

    run.log_output(tmp_path / "data" / "missing.txt")

    assert calls == []
    assert "No such file or directory" in caplog.text

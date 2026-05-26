import json
from pathlib import Path
from typing import Any

import attrs
import pytest

from liblaf.cherries import core


@attrs.define
class AssetRecorder(core.Plugin):
    calls: list[tuple[str, Path, Path, bool]]

    @core.impl
    def log_asset(
        self, path: Path, name: Path, *, report: bool = True, **_kwargs: Any
    ) -> None:
        self.calls.append(("asset", path, name, report))

    @core.impl
    def log_input(
        self, path: Path, name: Path, *, report: bool = True, **_kwargs: Any
    ) -> None:
        self.calls.append(("input", path, name, report))

    @core.impl
    def log_output(
        self, path: Path, name: Path, *, report: bool = True, **_kwargs: Any
    ) -> None:
        self.calls.append(("output", path, name, report))

    @core.impl
    def log_temp(
        self, path: Path, name: Path, *, report: bool = True, **_kwargs: Any
    ) -> None:
        self.calls.append(("temp", path, name, report))


def test_path_helpers_queue_and_flush_existing_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = core.Run()
    monkeypatch.setattr(run, "exp_dir", tmp_path)
    calls: list[tuple[str, Path, Path, bool]] = []
    run.register(AssetRecorder(calls))

    asset = run.asset("figs/plot.txt", mkdir=True)
    input_ = run.input("raw/data.csv", mkdir=True)
    output = run.output("metrics.json", mkdir=True)
    temp = run.temp("scratch/state.txt", mkdir=True)
    for path in (asset, input_, output, temp):
        path.write_text(path.name)

    run.end()

    assert calls == [
        ("asset", asset.resolve(), Path("figs/plot.txt"), True),
        ("input", input_.resolve(), Path("raw/data.csv"), True),
        ("output", output.resolve(), Path("metrics.json"), True),
        ("temp", temp.resolve(), Path("scratch/state.txt"), True),
    ]


def test_log_output_expands_series_bundles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = core.Run()
    monkeypatch.setattr(run, "exp_dir", tmp_path)
    calls: list[tuple[str, Path, Path, bool]] = []
    run.register(AssetRecorder(calls))

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

    run.log_output(series)

    assert calls == [
        ("output", series.resolve(), Path("mesh.vtp.series"), True),
        (
            "output",
            frames[0],
            Path("mesh.vtp.series.d/mesh_000000.vtp"),
            False,
        ),
        (
            "output",
            frames[1],
            Path("mesh.vtp.series.d/mesh_000001.vtp"),
            False,
        ),
    ]


def test_missing_artifact_warns_without_delegating(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = core.Run()
    monkeypatch.setattr(run, "exp_dir", tmp_path)
    calls: list[tuple[str, Path, Path, bool]] = []
    run.register(AssetRecorder(calls))

    run.log_output(tmp_path / "data" / "missing.txt")

    assert calls == []
    assert "No such file or directory" in caplog.text

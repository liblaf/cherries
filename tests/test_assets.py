from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries.core.assets import AssetsManager
from liblaf.cherries.core.assets.bundle import BundleRegistry


class RecordingAssetPlugin:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, dict[str, Any] | None, bool]] = []

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


def manager_for(tmp_path: Path, plugin: RecordingAssetPlugin) -> AssetsManager:
    return AssetsManager(
        working_dir=tmp_path,
        plugins=plugin,
        bundles=BundleRegistry(registry=[]),
    )


def test_input_logs_existing_data_path_immediately(tmp_path: Path) -> None:
    plugin = RecordingAssetPlugin()
    manager = manager_for(tmp_path, plugin)
    raw = tmp_path / "data" / "raw.csv"
    raw.parent.mkdir()
    raw.write_text("x,y\n1,2\n")

    result = manager.input("raw.csv", metadata={"split": "train"})

    assert result == raw
    assert manager.summary.inputs == [raw]
    assert plugin.calls == [(raw, {"type": "input", "split": "train"}, True)]


def test_output_and_temp_paths_are_queued_until_end(tmp_path: Path) -> None:
    plugin = RecordingAssetPlugin()
    manager = manager_for(tmp_path, plugin)

    output = manager.output("nested/result.txt", metadata={"format": "text"})
    temp = manager.temp("scratch/cache.bin", mkdir=False)

    assert output.parent.is_dir()
    assert plugin.calls == []

    output.write_text("ok\n")
    temp.parent.mkdir(parents=True)
    temp.write_bytes(b"ok")
    manager.end()

    assert manager.summary.outputs == [output]
    assert manager.summary.temps == [temp]
    assert plugin.calls == [
        (output, {"type": "output", "format": "text"}, True),
        (temp, {"type": "temp"}, True),
    ]


def test_missing_queued_artifact_warns_without_reporting(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    plugin = RecordingAssetPlugin()
    manager = manager_for(tmp_path, plugin)
    missing = manager.output("missing.txt", mkdir=False)

    with caplog.at_level(
        logging.WARNING, logger="liblaf.cherries.core.assets._manager"
    ):
        manager.end()

    assert missing.exists() is False
    assert manager.summary.outputs == []
    assert plugin.calls == []
    assert f"No such file or directory: {missing}" in caplog.text


def test_log_asset_reports_primary_and_silent_bundle_companions(tmp_path: Path) -> None:
    plugin = RecordingAssetPlugin()
    manager = AssetsManager(working_dir=tmp_path, plugins=plugin)
    mesh = tmp_path / "mesh.vtu"
    landmarks = tmp_path / "mesh.landmarks.json"
    mesh.write_text("<VTKFile />\n")
    landmarks.write_text("{}\n")

    manager.log_output(mesh, metadata={"kind": "mesh"})

    assert manager.summary.outputs == [mesh]
    assert plugin.calls == [
        (mesh, {"type": "output", "kind": "mesh"}, True),
        (landmarks, {"type": "output", "kind": "mesh"}, False),
    ]

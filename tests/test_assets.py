# Copyright (c) 2026 liblaf
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries.core.assets import AssetsManager
from liblaf.cherries.core.assets.bundle import BundleRegistry


class RecordingAssetPlugin:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Any, bool]] = []

    def log_asset(
        self,
        path: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        report: bool = True,
    ) -> None:
        self.calls.append((path, metadata, report))


def manager_for(tmp_path: Path) -> AssetsManager:
    return AssetsManager(
        working_dir=tmp_path / "work",
        plugins=RecordingAssetPlugin(),
        active=True,
        bundles=BundleRegistry(registry=[]),
    )


def test_input_is_an_independent_verified_copy(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n")
    staged = manager.input(source, name="nested/mesh.csv")
    assert staged == tmp_path / "work/inputs/nested/mesh.csv"
    assert staged.read_bytes() == source.read_bytes()
    assert not staged.samefile(source)
    staged.write_text("different")
    assert source.read_text() == "x,y\n1,2\n"


def test_required_missing_output_fails_and_scratch_is_disposable(
    tmp_path: Path,
) -> None:
    manager = manager_for(tmp_path)
    output = manager.output("result.txt")
    scratch = manager.temp("unused-cache.bin")
    with pytest.raises(FileNotFoundError, match="Required output"):
        manager.end()
    output.write_text("ok")
    manager.end()
    assert manager.summary.outputs == [output]
    assert not scratch.exists()
    assert manager.summary.temps == []


def test_helpers_outside_main_fail(tmp_path: Path) -> None:
    manager = manager_for(tmp_path)
    manager.active = False
    with pytest.raises(RuntimeError, match="inside main"):
        manager.output("result.txt")


def test_input_rejects_unhydrated_lfs_pointer(tmp_path: Path) -> None:
    pointer = tmp_path / "mesh.vtu"
    pointer.write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:"
        + "0" * 64
        + "\nsize 1000\n"
    )
    with pytest.raises(ValueError, match="unhydrated Git LFS"):
        manager_for(tmp_path).input(pointer)


@pytest.mark.parametrize("name", ["../outside", "/absolute"])
def test_output_rejects_escaping_paths(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="contained relative"):
        manager_for(tmp_path).output(name)


def test_required_series_companions_are_copied_and_missing_fails(
    tmp_path: Path,
) -> None:
    manager = manager_for(tmp_path)
    manager.bundles = BundleRegistry()
    series = tmp_path / "mesh.series"
    series.write_text(
        '{"file-series-version":"1.0","files":[{"name":"mesh-0.vtu","time":0}]}'
    )
    with pytest.raises(FileNotFoundError, match="companion"):
        manager.input(series)
    (tmp_path / "mesh-0.vtu").write_text("mesh")
    manager = manager_for(tmp_path / "second")
    manager.bundles = BundleRegistry()
    staged = manager.input(series)
    assert (staged.parent / "mesh-0.vtu").read_text() == "mesh"

import json
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries.bundle import BundleSeries


def generate_series_file(file: Path, *, frames: int = 10) -> None:
    files: list[dict[str, Any]] = []
    for i in range(frames):
        item: dict[str, Any] = {
            "name": f"{file.name}.d/{file.stem}_{i:06d}{file.suffix}",
            "time": i,
        }
        files.append(item)
    body: dict[str, Any] = {"file-series-version": "1.0", "files": files}
    with file.open("w") as fp:
        json.dump(body, fp)


@pytest.mark.parametrize("frames", [30])
def test_bundle_series(tmp_path: Path, *, frames: int) -> None:
    series_file: Path = tmp_path / "mesh.vtp.series"
    generate_series_file(series_file, frames=frames)
    bundle = BundleSeries()
    assert bundle.match(series_file)
    n_files: int = 0
    for absolute, relative, required in bundle.ls_files(series_file, tmp_path):
        assert absolute == tmp_path / relative
        assert required
        n_files += 1
    assert n_files == frames

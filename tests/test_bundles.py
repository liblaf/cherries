from __future__ import annotations

from pathlib import Path

from liblaf.cherries.core.assets.bundle import (
    BundleItem,
    BundleLandmarks,
    BundleRegistry,
    BundleSeries,
)


def test_series_bundle_yields_required_frame_paths(tmp_path: Path) -> None:
    series = tmp_path / "result.series"
    frame = tmp_path / "result_000.vtu"
    series.write_text(
        """
        {
          "file-series-version": "1.0",
          "files": [{"name": "result_000.vtu", "time": 0.0}]
        }
        """
    )

    bundle = BundleSeries()

    assert bundle.match(series)
    assert list(bundle.ls_files(series)) == [BundleItem(frame, optional=False)]


def test_landmark_bundle_is_optional_for_supported_meshes(tmp_path: Path) -> None:
    mesh = tmp_path / "face.vtp"
    bundle = BundleLandmarks()

    assert bundle.match(mesh)
    assert list(bundle.ls_files(mesh)) == [
        BundleItem(tmp_path / "face.landmarks.json", optional=True)
    ]
    assert bundle.match(tmp_path / "notes.txt") is False


def test_bundle_registry_expands_all_matching_bundles(tmp_path: Path) -> None:
    mesh = tmp_path / "face.vtu"
    registry = BundleRegistry(registry=[BundleLandmarks()])

    assert list(registry.ls_files(mesh)) == [
        BundleItem(tmp_path / "face.landmarks.json", optional=True)
    ]

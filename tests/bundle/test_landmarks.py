from collections.abc import Iterable
from pathlib import Path

from liblaf.cherries.bundle import Bundle, BundleItem, BundleLandmarks, BundleRegistry


def test_bundle_landmarks_matches_mesh_suffixes_and_yields_optional_file(
    tmp_path: Path,
) -> None:
    mesh = tmp_path / "mesh.vtp"
    bundle = BundleLandmarks()

    assert bundle.match(mesh)
    assert not bundle.match(tmp_path / "notes.txt")
    assert list(bundle.ls_files(mesh, tmp_path)) == [
        BundleItem(
            tmp_path / "mesh.landmarks.json",
            Path("mesh.landmarks.json"),
            optional=True,
        )
    ]


def test_bundle_registry_uses_registered_bundle(tmp_path: Path) -> None:
    class RelatedBundle(Bundle):
        def match(self, path: Path) -> bool:
            return path.suffix == ".primary"

        def ls_files(self, path: Path, prefix: Path) -> Iterable[BundleItem]:
            related = path.with_suffix(".related")
            yield BundleItem(related, related.relative_to(prefix), optional=False)

    primary = tmp_path / "case.primary"
    registry = BundleRegistry(registry=[])
    registry.register(RelatedBundle())

    assert list(registry.ls_files(primary, tmp_path)) == [
        BundleItem(tmp_path / "case.related", Path("case.related"), optional=False)
    ]

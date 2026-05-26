from collections.abc import Generator
from pathlib import Path
from typing import override

import attrs

from ._abc import Bundle, BundleItem
from ._utils import relative_or_name


@attrs.define
class BundleLandmarks(Bundle):
    """Bundle mesh files with optional sibling `.landmarks.json` annotations."""

    suffixes: set[str] = attrs.field(
        factory=lambda: {
            ".obj",
            ".ply",
            ".stl",
            ".vti",
            ".vtk",
            ".vtp",
            ".vtr",
            ".vts",
            ".vtu",
        }
    )

    @override
    def match(self, path: Path) -> bool:
        """Return whether `path` is a mesh file that may have landmarks."""
        return path.suffix in self.suffixes

    @override
    def ls_files(self, path: Path, prefix: Path) -> Generator[BundleItem]:
        """Yield the optional landmarks file next to `path`."""
        absolute: Path = path.with_suffix(".landmarks.json")
        yield BundleItem(absolute, relative_or_name(absolute, prefix), optional=True)

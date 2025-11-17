from collections.abc import Generator
from pathlib import Path
from typing import override

import attrs

from ._abc import Bundle, BundleItem
from ._utils import relative_to_or_name


@attrs.define
class BundleLandmarks(Bundle):
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
        return path.suffix in self.suffixes

    @override
    def ls_files(self, path: Path, prefix: Path) -> Generator[BundleItem]:
        absolute: Path = path.with_suffix(".landmarks.json")
        yield BundleItem(
            absolute, relative_to_or_name(absolute, prefix), required=False
        )

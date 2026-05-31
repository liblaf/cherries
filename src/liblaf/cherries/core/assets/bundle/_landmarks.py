from collections.abc import Generator
from pathlib import Path
from typing import override

import attrs

from ._abc import Bundle, BundleItem


@attrs.define
class BundleLandmarks(Bundle):
    suffixes: set[str] = attrs.field(
        factory=lambda: {
            ".obj",
            ".ply",
            ".stl",
            ".vti",
            ".vtkhdf",
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
    def ls_files(self, path: Path) -> Generator[BundleItem]:
        absolute: Path = path.with_suffix(".landmarks.json")
        yield BundleItem(absolute, optional=True)

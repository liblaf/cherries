from collections.abc import Generator
from pathlib import Path
from typing import override

import attrs

from ._abc import Bundle, BundleItem


@attrs.define
class BundleLandmarks(Bundle):
    """Expand mesh artifacts to an optional sibling landmark file.

    Cherries treats files such as `mesh.vtu` and `mesh.stl` as primary mesh
    artifacts. When a sibling `mesh.landmarks.json` exists, the file is logged
    with the primary artifact; when it is absent, no warning is emitted.
    """

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
        """Return whether `path` has a supported mesh suffix."""
        return path.suffix in self.suffixes

    @override
    def ls_files(self, path: Path) -> Generator[BundleItem]:
        """Yield the optional `.landmarks.json` companion for `path`."""
        absolute: Path = path.with_suffix(".landmarks.json")
        yield BundleItem(absolute, optional=True)

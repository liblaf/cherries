from collections.abc import Generator
from pathlib import Path
from typing import override

import attrs

from ._abc import AssetResolver


@attrs.define
class AssetResolverVtk(AssetResolver):
    SUFFIXES: set[str] = attrs.field(
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
        return path.suffix in self.SUFFIXES

    @override
    def resolve(self, path: Path) -> Generator[Path]:
        if (landmarks := path.with_suffix(".landmarks.json")).exists():
            yield landmarks

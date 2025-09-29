from collections.abc import Generator
from pathlib import Path
from typing import override

from ._abc import AssetResolver


class AssetResolverSeries(AssetResolver):
    @override
    def match(self, path: Path) -> bool:
        return path.suffix == ".series"

    @override
    def resolve(self, path: Path) -> Generator[Path]:
        if (folder := path.with_suffix(".d")).exists():
            yield folder
        if (folder := path.with_suffix("")).exists():
            yield folder

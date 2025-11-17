import os
from collections.abc import Generator
from pathlib import Path

import attrs

from ._abc import Bundle, BundleItem
from ._utils import relative_to_or_name

type PathLike = str | os.PathLike[str]


@attrs.define
class BundleRegistry:
    registry: list[Bundle] = attrs.field(factory=list)

    def ls_files(self, path: PathLike, prefix: PathLike) -> Generator[BundleItem]:
        path: Path = Path(path).resolve()
        prefix: Path = Path(prefix).resolve()
        yield BundleItem(path, relative_to_or_name(path, prefix), required=True)
        for bundle in self.registry:
            if bundle.match(path):
                yield from bundle.ls_files(path, prefix)


bundles: BundleRegistry = BundleRegistry()

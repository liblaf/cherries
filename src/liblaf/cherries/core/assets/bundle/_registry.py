from collections.abc import Generator
from pathlib import Path

import attrs

from ._abc import Bundle, BundleItem


@attrs.define
class BundleRegistry:
    @staticmethod
    def _default_registry() -> list[Bundle]:
        from ._landmarks import BundleLandmarks
        from ._series import BundleSeries

        return [BundleLandmarks(), BundleSeries()]

    registry: list[Bundle] = attrs.field(factory=_default_registry)

    def ls_files(self, path: Path) -> Generator[BundleItem]:
        for bundle in self.registry:
            if bundle.match(path):
                yield from bundle.ls_files(path)

    def register(self, bundle: Bundle) -> None:
        self.registry.append(bundle)


bundles: BundleRegistry = BundleRegistry()

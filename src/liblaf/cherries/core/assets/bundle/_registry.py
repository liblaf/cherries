from collections.abc import Generator
from pathlib import Path

import attrs

from ._abc import Bundle, BundleItem


@attrs.define
class BundleRegistry:
    """Registry that expands logged artifacts through matching bundles.

    Examples:
        >>> registry = BundleRegistry(registry=[])
        >>> list(registry.ls_files(Path("mesh.vtu")))
        []
    """

    @staticmethod
    def _default_registry() -> list[Bundle]:
        from ._landmarks import BundleLandmarks
        from ._series import BundleSeries

        return [BundleLandmarks(), BundleSeries()]

    registry: list[Bundle] = attrs.field(factory=_default_registry)

    def ls_files(self, path: Path) -> Generator[BundleItem]:
        """Yield companion files from every bundle that matches `path`."""
        for bundle in self.registry:
            if bundle.match(path):
                yield from bundle.ls_files(path)

    def register(self, bundle: Bundle) -> None:
        """Append `bundle` to the registry."""
        self.registry.append(bundle)


bundles: BundleRegistry = BundleRegistry()

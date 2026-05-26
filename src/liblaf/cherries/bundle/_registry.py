from collections.abc import Generator
from pathlib import Path

import attrs

from ._abc import Bundle, BundleItem


@attrs.define
class BundleRegistry:
    """Registry of bundle handlers used by [`Run`][liblaf.cherries.core.Run].

    The default registry expands VTK `.series` manifests and optional landmark
    files for mesh artifacts. Register custom bundles when one logged file
    implies additional companion files.
    """

    @staticmethod
    def _default_registry() -> list[Bundle]:
        from ._landmarks import BundleLandmarks
        from ._series import BundleSeries

        return [BundleLandmarks(), BundleSeries()]

    registry: list[Bundle] = attrs.field(factory=_default_registry)

    def ls_files(self, path: Path, prefix: Path) -> Generator[BundleItem]:
        """Yield related files from every bundle that matches `path`."""
        for bundle in self.registry:
            if bundle.match(path):
                yield from bundle.ls_files(path, prefix)

    def register(self, bundle: Bundle) -> None:
        """Add `bundle` to the registry."""
        self.registry.append(bundle)


bundles: BundleRegistry = BundleRegistry()

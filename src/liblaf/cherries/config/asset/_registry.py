from collections.abc import Generator
from pathlib import Path

import attrs

from .resolvers import AssetResolver, AssetResolverSeries, AssetResolverVtk


@attrs.define
class AssetResolverRegistry:
    _registry: dict[str, AssetResolver] = attrs.field(factory=dict)

    def register(self, resolver: AssetResolver) -> None:
        self._registry[resolver.id] = resolver

    def resolve(self, path: Path) -> Generator[Path]:
        for resolver in self._registry.values():
            if not resolver.match(path):
                continue
            yield from resolver.resolve(path)


asset_resolver_registry: AssetResolverRegistry = AssetResolverRegistry()
asset_resolver_registry.register(AssetResolverSeries())
asset_resolver_registry.register(AssetResolverVtk())

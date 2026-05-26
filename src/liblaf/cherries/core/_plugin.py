from __future__ import annotations

from typing import Any

import attrs

from ._typing import PluginName


@attrs.define
class Plugin:
    """Base class for Cherries plugins.

    Plugins implement hook methods decorated with
    [`impl`][liblaf.cherries.core.impl]. Register them on a
    [`PluginManager`][liblaf.cherries.core.PluginManager] or
    [`Run`][liblaf.cherries.core.Run] before delegating hooks.

    Examples:
        >>> Plugin().name
        'Plugin'
        >>> Plugin(name="custom").name
        'custom'
    """

    def _default_name(self: Plugin) -> PluginName:
        return type(self).__name__

    name: PluginName = attrs.field(
        default=attrs.Factory(_default_name, takes_self=True), kw_only=True
    )
    """Name used by hook ordering constraints."""

    manager: Any = attrs.field(default=None, repr=False, init=False, kw_only=True)
    """Manager this plugin is registered on."""

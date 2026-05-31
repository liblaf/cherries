from __future__ import annotations

import attrs

from ._typing import PluginName


@attrs.define
class Plugin:
    """Base class for Cherries plugins.

    Attributes:
        name: Unique name used by the plugin manager and hook ordering rules.
            Defaults to the concrete class name.
    """

    def _default_name(self: Plugin) -> PluginName:
        return type(self).__name__

    name: PluginName = attrs.field(
        default=attrs.Factory(_default_name, takes_self=True), kw_only=True
    )

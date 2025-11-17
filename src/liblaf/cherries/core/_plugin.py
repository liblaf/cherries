from __future__ import annotations

from typing import TYPE_CHECKING

import attrs

from ._typing import PluginId

if TYPE_CHECKING:
    from ._plugin_manager import PluginManager


def _default_id(self: Plugin) -> PluginId:
    return type(self).__name__


@attrs.define
class Plugin:
    id: PluginId = attrs.field(
        default=attrs.Factory(_default_id, takes_self=True), kw_only=True
    )
    manager: PluginManager = attrs.field(
        default=None, repr=False, init=False, kw_only=True
    )

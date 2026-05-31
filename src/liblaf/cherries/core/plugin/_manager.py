from __future__ import annotations

import functools
import graphlib
import logging
from collections.abc import Callable, Sequence
from typing import Any

import attrs

from ._impl import ImplInfo, get_impl_info
from ._plugin import Plugin
from ._typing import MethodName, PluginName

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class PluginManager:
    registry: dict[PluginName, Plugin] = attrs.field(factory=dict, kw_only=True)

    def __getattr__(self, name: str) -> Any:
        return functools.partial(self.delegate, name)

    def register(self, plugin: Plugin) -> None:
        self.registry[plugin.name] = plugin
        self._sort_plugins_cache.clear()

    def delegate(self, method: MethodName, *args, **kwargs) -> Any:
        for plugin in self._sort_plugins(method):
            try:
                getattr(plugin, method)(*args, **kwargs)
            except Exception:
                logger.exception("")

    _sort_plugins_cache: dict[MethodName, Sequence[Plugin]] = attrs.field(
        repr=False, init=False, factory=dict
    )

    def _sort_plugins(self, method_name: MethodName) -> Sequence[Plugin]:
        if method_name not in self._sort_plugins_cache:
            plugins: dict[PluginName, Plugin] = {}
            sorter: graphlib.TopologicalSorter[PluginName] = (
                graphlib.TopologicalSorter()
            )
            for plugin in self.registry.values():
                method: Callable | None = getattr(plugin, method_name, None)
                impl_info: ImplInfo | None = get_impl_info(method)
                if impl_info is None:
                    continue
                plugins[plugin.name] = plugin
                sorter.add(plugin.name, *impl_info.after)
                for before in impl_info.before:
                    sorter.add(before, plugin.name)
            plugins_sorted: list[Plugin] = []
            for plugin_name in sorter.static_order():
                plugin: Plugin | None = plugins.get(plugin_name)
                if plugin is None:
                    continue
                plugins_sorted.append(plugin)
            self._sort_plugins_cache[method_name] = plugins_sorted
        return self._sort_plugins_cache[method_name]

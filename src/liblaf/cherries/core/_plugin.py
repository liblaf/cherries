import math
import operator
from collections.abc import Mapping, Sequence
from typing import Any, Self

import attrs
import cachetools
import networkx as nx
from loguru import logger

from ._impl import ImplInfo, collect_impls, get_impl_info
from .typing import MethodName, PluginId


@attrs.define
class Plugin:
    plugins: dict[PluginId, "Plugin"] = attrs.field(factory=dict, kw_only=True)

    _plugin_parent: Self | None = attrs.field(default=None, kw_only=True)
    _cache_sort_plugins: cachetools.Cache[MethodName, Sequence["Plugin"]] = attrs.field(
        factory=lambda: cachetools.Cache(math.inf), init=False
    )

    @property
    def plugin_id(self) -> str:
        return type(self).__name__

    @property
    def plugin_root(self) -> Self:
        if self._plugin_parent is None:
            return self
        return self._plugin_parent.plugin_root

    def delegate(
        self,
        method: MethodName,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] = {},
        *,
        first_result: bool = False,
    ) -> Any:
        plugins: Sequence[Plugin] = self._plugins_sort(method)
        if not plugins:
            if first_result:
                return None
            return []
        results: list[Any] = []
        for plugin in plugins:
            try:
                result: Any = getattr(plugin, method)(*args, **kwargs)
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.exception("Plugin {}", plugin.plugin_id)
            else:
                if result is None:
                    continue
                if first_result:
                    return result
                results.append(result)
        return results

    def register(self, plugin: "Plugin") -> None:
        impls: dict[MethodName, ImplInfo] = collect_impls(plugin)
        for name in impls:
            self._cache_sort_plugins.pop(name, None)
        plugin._plugin_parent = self  # noqa: SLF001
        self.plugins[plugin.plugin_id] = plugin

    def _plugins_sort_cache_key(self, method: MethodName) -> MethodName:
        return method

    @cachetools.cachedmethod(
        operator.attrgetter("_cache_sort_plugins"), key=_plugins_sort_cache_key
    )
    def _plugins_sort(self, method: str) -> Sequence["Plugin"]:
        plugin_infos: dict[str, ImplInfo] = {
            plugin_id: info
            for plugin_id, plugin in self.plugins.items()
            if (info := get_impl_info(getattr(plugin, method, None))) is not None
        }

        def key_fn(node: str) -> int:
            return plugin_infos[node].priority

        graph: nx.DiGraph[str] = nx.DiGraph()
        for plugin_id, impl_info in plugin_infos.items():
            graph.add_node(plugin_id)
            for after in impl_info.after:
                if after in plugin_infos:
                    graph.add_edge(after, plugin_id)
            for before in impl_info.before:
                if before in plugin_infos:
                    graph.add_edge(plugin_id, before)
        return tuple(
            plugin
            for plugin_id in nx.lexicographical_topological_sort(graph, key=key_fn)
            if (plugin := self.plugins.get(plugin_id)) is not None
        )

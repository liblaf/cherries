from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any, Self

import attrs
import networkx as nx

from ._impl import ImplInfo, get_impl_info
from ._spec import SpecInfo, collect_specs
from .typed import MethodName


@attrs.define
class Plugin:
    plugins: dict[str, "Plugin"] = attrs.field(factory=dict, kw_only=True)

    _plugin_parent: Self | None = attrs.field(default=None, kw_only=True)
    _sort_plugins_cache: MutableMapping[MethodName, Sequence["Plugin"]] = attrs.field(
        factory=dict, init=False
    )

    @classmethod
    def plugin_id_cls(cls) -> str:
        return cls.__name__

    @property
    def plugin_id(self) -> str:
        return self.plugin_id_cls()

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
            result: Any = getattr(plugin, method)(*args, **kwargs)
            if result is None:
                continue
            if first_result:
                return result
            results.append(result)
        return results

    def register(self, plugin: "Plugin") -> None:
        plugin._plugin_parent = self  # noqa: SLF001
        self.plugins[plugin.plugin_id] = plugin

    def _plugins_prepare(self) -> None:
        specs: dict[str, SpecInfo] = collect_specs(self)
        for method in specs:
            self._sort_plugins_cache[method] = self._plugins_sort(
                method, refresh_cache=True
            )

    def _plugins_sort(
        self, method: str, *, refresh_cache: bool = False
    ) -> Sequence["Plugin"]:
        if refresh_cache or method not in self._sort_plugins_cache:
            plugin_infos: dict[str, ImplInfo] = {
                plugin_id: info
                for plugin_id, plugin in self.plugins.items()
                if (info := get_impl_info(getattr(plugin, method, None))) is not None
            }

            def key_fn(node: str) -> int:
                return plugin_infos[node].priority

            graph = nx.DiGraph()
            for plugin_id, impl_info in plugin_infos.items():
                graph.add_node(plugin_id)
                for after in impl_info.after:
                    if after in plugin_infos:
                        graph.add_edge(after, plugin_id)
                for before in impl_info.before:
                    if before in plugin_infos:
                        graph.add_edge(plugin_id, before)
            self._sort_plugins_cache[method] = tuple(
                plugin
                for plugin_id in nx.lexicographical_topological_sort(graph, key=key_fn)
                if (plugin := self.plugins.get(plugin_id)) is not None
            )
        return self._sort_plugins_cache[method]

import inspect
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any, Self

import attrs
import networkx as nx

from ._impl import ImplInfo, get_impl_info
from ._spec import SpecInfo
from .typed import MethodName


@attrs.define
class Plugin:
    plugins: dict[str, "Plugin"] = attrs.field(factory=dict)

    _plugin_parent: Self | None = attrs.field(default=None)
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

    @property
    def specs(self) -> dict[str, SpecInfo]:
        return {
            name: method._self_spec  # noqa: SLF001
            for name, method in inspect.getmembers(
                type(self), lambda m: getattr(m, "_self_spec", None) is not None
            )
        }

    def delegate(
        self,
        method: MethodName,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] = {},
        *,
        first_result: bool = False,
    ) -> Any:
        results: list[Any] = []
        for plugin in self._sort_plugins_cache.get(method, []):
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

    def _prepare(self) -> None:
        for method in self.specs:
            self._sort_plugins_cache[method] = self._sort_plugins(
                method, refresh_cache=True
            )

    def _sort_plugins(
        self, method: str, *, refresh_cache: bool = False
    ) -> Sequence["Plugin"]:
        if refresh_cache or method not in self._sort_plugins_cache:
            plugin_infos: dict[str, ImplInfo] = {
                plugin_id: info
                for plugin_id, plugin in self.plugins.items()
                if (info := get_impl_info(getattr(plugin, method, None))) is not None
            }
            graph = nx.DiGraph()
            for plugin_id, impl_info in plugin_infos.items():
                graph.add_node(plugin_id)
                for after in impl_info.after:
                    graph.add_edge(after, plugin_id)
                for before in impl_info.before:
                    graph.add_edge(plugin_id, before)
            self._sort_plugins_cache[method] = tuple(
                plugin
                for plugin_id in nx.lexicographical_topological_sort(
                    graph, key=lambda node: plugin_infos[node].priority
                )
                if (plugin := self.plugins.get(plugin_id)) is not None
            )
        return self._sort_plugins_cache[method]

from __future__ import annotations

import functools
import graphlib
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, overload

import attrs
import cachetools
import wrapt

from ._impl import ImplInfo, collect_impls, get_impl_info
from ._typing import MethodName, PluginId

if TYPE_CHECKING:
    from ._plugin import Plugin


logger: logging.Logger = logging.getLogger(__name__)


@overload
def delegate[C: Callable](func: C, /, *, first_result: bool = False) -> C: ...
@overload
def delegate[C: Callable](*, first_result: bool = False) -> Callable[[C], C]: ...
def delegate(func: Callable | None = None, *, first_result: bool = False) -> Any:
    if func is None:
        return functools.partial(delegate, first_result=first_result)

    @wrapt.decorator
    def wrapper(
        wrapped: Callable,
        instance: PluginManager,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        __tracebackhide__ = True
        return instance.delegate(
            method=wrapped.__name__, args=args, kwargs=kwargs, first_result=first_result
        )

    return wrapper(func)


@attrs.define
class PluginManager:
    plugins: dict[PluginId, Plugin] = attrs.field(factory=dict, kw_only=True)

    def register(self, plugin: Plugin) -> None:
        for method_name in collect_impls(plugin):
            self._sort_plugins_cache.pop(method_name, None)
        plugin.manager = self
        self.plugins[plugin.id] = plugin

    def delegate(
        self,
        method: MethodName,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] = {},
        *,
        first_result: bool = False,
    ) -> Any:
        __tracebackhide__ = True
        results: list[Any] = []
        for plugin in self._sort_plugins(method):
            try:
                result: Any = getattr(plugin, method)(*args, **kwargs)
            except Exception:
                logger.exception("Plugin %s", plugin.id)
            else:
                if result is None:
                    continue
                if first_result:
                    return result
                results.append(result)
        if first_result:
            return None
        return results

    _sort_plugins_cache: cachetools.Cache[MethodName, Sequence[Plugin]] = attrs.field(
        repr=False, init=False, factory=lambda: cachetools.Cache(math.inf)
    )

    def _sort_plugins_key(self, method_name: MethodName) -> MethodName:
        return method_name

    @cachetools.cachedmethod(
        lambda self: self._sort_plugins_cache, key=_sort_plugins_key
    )
    def _sort_plugins(self, method_name: MethodName) -> Sequence[Plugin]:
        plugins: dict[PluginId, Plugin] = {}
        sorter: graphlib.TopologicalSorter[PluginId] = graphlib.TopologicalSorter()
        for plugin in self.plugins.values():
            method: Callable | None = getattr(plugin, method_name, None)
            impl_info: ImplInfo | None = get_impl_info(method)
            if impl_info is None:
                continue
            plugins[plugin.id] = plugin
            sorter.add(plugin.id, *impl_info.after)
            for before_id in impl_info.before:
                sorter.add(before_id, plugin.id)
        plugins_sorted: list[Plugin] = []
        for plugin_id in sorter.static_order():
            plugin: Plugin | None = plugins.get(plugin_id)
            if plugin is None:
                continue
            plugins_sorted.append(plugin)
        return plugins_sorted

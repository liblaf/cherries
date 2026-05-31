from __future__ import annotations

import functools
import graphlib
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, overload

import attrs

from ._impl import ImplInfo, get_impl_info
from ._typing import MethodName, PluginName

if TYPE_CHECKING:
    from ._plugin import Plugin


logger: logging.Logger = logging.getLogger(__name__)


@overload
def delegate[F: Callable[..., Any]](func: F, /, *, first_result: bool = False) -> F: ...
@overload
def delegate[F: Callable[..., Any]](
    *, first_result: bool = False
) -> Callable[[F], F]: ...
def delegate(
    func: Callable[..., Any] | None = None, *, first_result: bool = False
) -> Any:
    """Build a method that delegates to registered plugin implementations.

    Args:
        func: Method being decorated.
        first_result: Return the first non-`None` plugin result instead of a
            list of all non-`None` results.
    """
    if func is None:
        return functools.partial(delegate, first_result=first_result)
    method_name: MethodName = func.__name__  # ty:ignore[unresolved-attribute]

    @functools.wraps(func)
    def wrapper(self: PluginManager, *args: Any, **kwargs: Any) -> Any:
        return self.delegate(method_name, args, kwargs, first_result=first_result)

    return wrapper


@attrs.define
class PluginManager:
    """Register plugins and delegate hook calls in dependency order.

    Examples:
        >>> from liblaf.cherries.core import Plugin, impl
        >>> calls = []
        >>> class Recorder(Plugin):
        ...     @impl
        ...     def start(self):
        ...         calls.append(self.name)
        >>> manager = PluginManager()
        >>> manager.register(Recorder())
        >>> manager.delegate("start")
        []
        >>> calls
        ['Recorder']
    """

    plugins: dict[PluginName, Plugin] = attrs.field(factory=dict, kw_only=True)
    """Registered plugins keyed by plugin name."""

    def register(self, plugin: Plugin) -> None:
        """Register `plugin` and invalidate cached orders for its hooks."""
        plugin.manager = self
        self.plugins[plugin.name] = plugin
        self._sort_plugins_cache.clear()

    def delegate(
        self,
        method: MethodName,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        *,
        first_result: bool = False,
    ) -> Any:
        """Call every plugin implementation for `method`.

        Exceptions raised by individual plugins are logged and do not stop
        later plugins from running.

        Args:
            method: Hook method name to call.
            args: Positional arguments passed to the hook.
            kwargs: Keyword arguments passed to the hook.
            first_result: Return the first non-`None` result.
        """
        __tracebackhide__ = True
        if kwargs is None:
            kwargs = {}
        results: list[Any] = []
        for plugin in self._sort_plugins(method):
            try:
                result: Any = getattr(plugin, method)(*args, **kwargs)
            except Exception:
                logger.exception("Plugin %s", plugin.name)
            else:
                if result is None:
                    continue
                if first_result:
                    return result
                results.append(result)
        if first_result:
            return None
        return results

    _sort_plugins_cache: dict[MethodName, Sequence[Plugin]] = attrs.field(
        repr=False, init=False, factory=dict
    )

    def _sort_plugins(self, method_name: MethodName) -> Sequence[Plugin]:
        if method_name not in self._sort_plugins_cache:
            plugins: dict[PluginName, Plugin] = {}
            sorter: graphlib.TopologicalSorter[PluginName] = (
                graphlib.TopologicalSorter()
            )
            for plugin in self.plugins.values():
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

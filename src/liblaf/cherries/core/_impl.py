import functools
import inspect
from collections.abc import Callable, Iterable
from typing import Any, overload

import attrs

from ._typing import MethodName, PluginName


@attrs.define
class ImplInfo:
    """Ordering metadata attached to a plugin hook implementation."""

    after: Iterable[PluginName] = ()
    """Plugin names that should run before this implementation."""

    before: Iterable[PluginName] = ()
    """Plugin names that should run after this implementation."""


@overload
def impl[F: Callable[..., Any]](
    func: F, /, *, after: Iterable[PluginName] = (), before: Iterable[PluginName] = ()
) -> F: ...
@overload
def impl[F: Callable[..., Any]](
    *, after: Iterable[PluginName] = (), before: Iterable[PluginName] = ()
) -> Callable[[F], F]: ...
def impl(func: Callable[..., Any] | None = None, /, **kwargs: Any) -> Any:
    """Mark a method as a plugin hook implementation.

    Args:
        func: Method being decorated.
        **kwargs: Ordering metadata accepted by [`ImplInfo`][liblaf.cherries.core.ImplInfo].

    Examples:
        >>> @impl(before=("Comet",))
        ... def log_metric():
        ...     return None
        >>> get_impl_info(log_metric).before
        ('Comet',)
    """
    if func is None:
        return functools.partial(impl, **kwargs)
    info = ImplInfo(**kwargs)
    func.__cherries_impl__ = info  # ty:ignore[unresolved-attribute]
    return func


def collect_impls(cls: Any) -> dict[MethodName, ImplInfo]:
    """Collect hook implementations declared on a plugin class or instance.

    Examples:
        >>> class Example:
        ...     @impl
        ...     def start(self):
        ...         return None
        >>> sorted(collect_impls(Example))
        ['start']
    """
    if not isinstance(cls, type):
        cls = type(cls)
    impls: dict[MethodName, ImplInfo] = {}
    for name, method in inspect.getmembers(cls):
        info: ImplInfo | None = get_impl_info(method)
        if info is not None:
            impls[name] = info
    return impls


def get_impl_info(func: Callable | None) -> ImplInfo | None:
    """Return hook metadata previously attached with [`impl`][liblaf.cherries.core.impl]."""
    if func is None:
        return None
    return getattr(func, "__cherries_impl__", None)

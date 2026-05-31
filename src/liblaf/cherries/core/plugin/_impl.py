import functools
from collections.abc import Callable, Iterable
from typing import Any, overload

import attrs

from ._typing import PluginName


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


def get_impl_info(func: Callable | None) -> ImplInfo | None:
    """Return hook metadata previously attached with [`impl`][liblaf.cherries.core.impl]."""
    if func is None:
        return None
    return getattr(func, "__cherries_impl__", None)

import functools
from collections.abc import Callable, Iterable
from typing import Any, overload

import attrs
import wrapt

from liblaf import grapes

from .typed import PluginId


@attrs.define
class ImplInfo:
    after: Iterable[PluginId] = attrs.field(default=())
    before: Iterable[PluginId] = attrs.field(default=())
    priority: int = 0


@overload
def impl[C: Callable](
    func: C,
    /,
    *,
    priority: int = 0,
    after: Iterable[PluginId] = (),
    before: Iterable[PluginId] = (),
) -> C: ...
@overload
def impl[C: Callable](
    *,
    priority: int = 0,
    after: Iterable[PluginId] = (),
    before: Iterable[PluginId] = (),
) -> Callable[[C], C]: ...
def impl(
    func: Callable | None = None,
    /,
    priority: int = 0,
    after: Iterable[PluginId] = (),
    before: Iterable[PluginId] = (),
) -> Any:
    if func is None:
        return functools.partial(impl, priority=priority, after=after, before=before)

    @wrapt.decorator
    def wrapper(
        wrapped: Callable, _instance: Any, args: tuple, kwargs: dict[str, Any]
    ) -> Any:
        return wrapped(*args, **kwargs)

    proxy: Any = wrapper(func)  # pyright: ignore[reportCallIssue]
    proxy._self_impl = ImplInfo(after=after, before=before, priority=priority)  # noqa: SLF001
    return proxy


def get_impl_info(func: Callable | None) -> ImplInfo | None:
    if func is None:
        return None
    return grapes.unbind_getattr(func, "_self_impl", None)

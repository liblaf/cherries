import functools
import inspect
from collections.abc import Callable, Iterable
from typing import Any, overload

import attrs

from liblaf import grapes

from .typing import MethodName, PluginId


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

    info = ImplInfo(after=after, before=before, priority=priority)

    @grapes.decorator
    def wrapper(
        wrapped: Callable, _instance: Any, args: tuple, kwargs: dict[str, Any]
    ) -> Any:
        return wrapped(*args, **kwargs)

    func = wrapper(func)
    grapes.wrapt_setattr(func, "impl", info)
    return func


def collect_impls(cls: Any) -> dict[MethodName, ImplInfo]:
    if isinstance(cls, type):
        cls = type(cls)
    return {
        name: grapes.wrapt_getattr(method, "impl")
        for name, method in inspect.getmembers(
            cls, lambda m: grapes.wrapt_getattr(m, "impl", None) is not None
        )
    }


def get_impl_info(func: Callable | None) -> ImplInfo | None:
    if func is None:
        return None
    return grapes.wrapt_getattr(func, "impl", None)

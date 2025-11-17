import functools
import inspect
from collections.abc import Callable, Iterable
from typing import Any, overload

import attrs
import wrapt

from liblaf import grapes

from ._typing import MethodName, PluginId


@attrs.define
class ImplInfo:
    after: Iterable[PluginId] = ()
    before: Iterable[PluginId] = ()


@overload
def impl[C: Callable](
    func: C, /, *, after: Iterable[PluginId] = (), before: Iterable[PluginId] = ()
) -> C: ...
@overload
def impl[C: Callable](
    *, after: Iterable[PluginId] = (), before: Iterable[PluginId] = ()
) -> Callable[[C], C]: ...
def impl[**P, T](func: Callable[P, T] | None = None, /, **kwargs) -> Any:
    if func is None:
        return functools.partial(impl, **kwargs)

    info = ImplInfo(**kwargs)

    @wrapt.decorator
    def wrapper(
        wrapped: Callable[P, T],
        _instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> T:
        __tracebackhide__ = True
        return wrapped(*args, **kwargs)

    func = wrapper(func)
    grapes.wrapt_setattr(func, "impl", info)
    return func


def collect_impls(cls: Any) -> dict[MethodName, ImplInfo]:
    if not isinstance(cls, type):
        cls = type(cls)
    impls: dict[MethodName, ImplInfo] = {}
    for name, method in inspect.getmembers(cls):
        info: ImplInfo | None = get_impl_info(method)
        if info is not None:
            impls[name] = info
    return impls


def get_impl_info(func: Callable | None) -> ImplInfo | None:
    if func is None:
        return None
    return grapes.wrapt_getattr(func, "impl", None)

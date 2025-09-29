import functools
import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, overload

import attrs

from liblaf import grapes

from .typing import MethodName


class Plugin(Protocol):
    def delegate(
        self,
        method: MethodName,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        *,
        first_result: bool = False,
    ) -> Any: ...


@attrs.define
class SpecInfo:
    delegate: bool = attrs.field(default=True)
    first_result: bool = attrs.field(default=False)


@overload
def spec[C: Callable](
    func: C, /, *, delegate: bool = True, first_result: bool = False
) -> C: ...
@overload
def spec[C: Callable](
    *, delegate: bool = True, first_result: bool = False
) -> Callable[[C], C]: ...
def spec(
    func: Callable | None = None,
    /,
    *,
    delegate: bool = True,
    first_result: bool = False,
) -> Any:
    if func is None:
        return functools.partial(spec, delegate=delegate, first_result=first_result)

    info = SpecInfo(delegate=delegate, first_result=first_result)

    @grapes.decorator
    def wrapper[**P, T](
        wrapped: Callable[P, T], instance: Plugin, args: tuple, kwargs: dict[str, Any]
    ) -> T:
        if info.delegate:
            return instance.delegate(
                wrapped.__name__, args, kwargs, first_result=info.first_result
            )
        return wrapped(*args, **kwargs)

    func: Any = wrapper(func)
    grapes.wrapt_setattr(func, "spec", info)
    return func


def collect_specs(cls: type[Plugin] | Plugin) -> dict[str, SpecInfo]:
    if isinstance(cls, type):
        cls = type(cls)
    return {
        name: grapes.wrapt_getattr(method, "spec")
        for name, method in inspect.getmembers(
            cls, lambda m: grapes.wrapt_getattr(m, "spec", None) is not None
        )
    }

import functools
import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, overload

import attrs

from liblaf import grapes

from .typed import MethodName


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

    @grapes.decorator(attrs={"_self_spec": info})
    def wrapper(
        wrapped: Callable, instance: Plugin, args: tuple, kwargs: dict[str, Any]
    ) -> Any:
        if info.delegate:
            return instance.delegate(
                wrapped.__name__, args, kwargs, first_result=info.first_result
            )
        return wrapped(*args, **kwargs)

    return wrapper(func)


def collect_specs(cls: type[Plugin] | Plugin) -> dict[str, SpecInfo]:
    if isinstance(cls, type):
        cls = type(cls)
    return {
        name: method._self_spec  # noqa: SLF001
        for name, method in inspect.getmembers(
            cls, lambda m: getattr(m, "_self_spec", None) is not None
        )
    }

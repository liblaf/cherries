import functools
import inspect
from collections.abc import Callable, Sequence
from typing import ParamSpec, TypeVar

from liblaf import cherries

_P = ParamSpec("_P")
_T = TypeVar("_T")


def main(
    *,
    backend: cherries.Backend | None = None,
    enabled: bool | None = None,
    plugins: Sequence[cherries.Plugin] | None = None,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def wrapper(fn: Callable[_P, _T]) -> Callable[_P, _T]:
        @functools.wraps(fn)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            exp: cherries.Experiment = cherries.start(
                backend=backend, enabled=enabled, plugins=plugins
            )
            sig: inspect.Signature = inspect.signature(fn)
            bound_args: inspect.BoundArguments = sig.bind(*args, **kwargs)
            if len(bound_args.arguments) == 1:
                exp.log_other(
                    "cherries/config", next(iter(bound_args.arguments.values()))
                )
            elif len(bound_args.arguments) > 1:
                exp.log_other("cherries/args", bound_args.arguments)
            ret: _T = fn(*args, **kwargs)
            exp.end()
            return ret

        return wrapped

    return wrapper

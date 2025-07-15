import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from liblaf.cherries import core, profiles


def end() -> None:
    core.active_run.end()


def run[T](main: Callable[..., T], *, profile: profiles.ProfileLike | None = None) -> T:
    run: core.Run = start(profile=profile)
    args: Sequence[Any]
    kwargs: Mapping[str, Any]
    args, kwargs = _make_args(main)
    # TODO: log config & inputs
    result: T = main(*args, **kwargs)
    # TODO: log outputs
    run.end()
    return result


def start(
    profile: profiles.ProfileLike | None = None,
) -> core.Run:
    run: core.Run = profiles.factory(profile).init()
    run.start()
    # TODO: log metadata
    return run


def _make_args(func: Callable) -> tuple[Sequence[Any], Mapping[str, Any]]:
    signature: inspect.Signature = inspect.signature(func)
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        match param.kind:
            case (
                inspect.Parameter.POSITIONAL_ONLY
                | inspect.Parameter.POSITIONAL_OR_KEYWORD
            ):
                args.append(_make_arg(param))
            case inspect.Parameter.KEYWORD_ONLY:
                kwargs[name] = _make_arg(param)
            case _:
                pass
    return args, kwargs


def _make_arg(param: inspect.Parameter) -> Any:
    if param.default is not inspect.Parameter.empty:
        return param.default
    if param.annotation is not inspect.Parameter.empty:
        return param.annotation()
    return None

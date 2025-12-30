import inspect
import typing
from collections.abc import Callable, Mapping, Sequence
from inspect import Parameter
from typing import Any

import pydantic

from liblaf.cherries import core, profiles

from ._start import start


def main[T](
    main: Callable[..., T], *, profile: profiles.ProfileLike | None = None
) -> T:
    run: core.Run = start(profile=profile)
    args: Sequence[Any]
    kwargs: Mapping[str, Any]
    args, kwargs = _make_args(main)
    configs: list[pydantic.BaseModel] = [
        arg for arg in (*args, *kwargs.values()) if isinstance(arg, pydantic.BaseModel)
    ]
    for config in configs:
        run.log_params(config.model_dump(mode="json"))
    try:
        return main(*args, **kwargs)
    finally:
        run.end()


def _make_args(func: Callable) -> tuple[Sequence[Any], Mapping[str, Any]]:
    hints: dict[str, Any] = typing.get_type_hints(func)
    signature: inspect.Signature = inspect.signature(func)
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        annotation: Any = hints.get(name)
        match param.kind:
            case Parameter.POSITIONAL_ONLY:
                args.append(_make_arg(param, annotation))
            case Parameter.POSITIONAL_OR_KEYWORD | Parameter.KEYWORD_ONLY:
                kwargs[name] = _make_arg(param, annotation)
            case _:
                pass
    return args, kwargs


def _make_arg(param: Parameter, annotation: Any) -> Any:
    if param.default is not Parameter.empty:
        return param.default
    if param.annotation is not Parameter.empty:
        if not isinstance(param.annotation, str):
            return param.annotation()
        if annotation is not None:
            return annotation()
    return None

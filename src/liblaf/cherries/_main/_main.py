import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from inspect import Parameter
from typing import Any, overload

import pydantic

from liblaf.cherries import core, profiles

from ._start import start


@overload
def main[T](
    main: Callable[..., Awaitable[T]], *, profile: profiles.ProfileLike | None = None
) -> T: ...
@overload
def main[T](
    main: Callable[..., T], *, profile: profiles.ProfileLike | None = None
) -> T: ...
def main[T](
    main: Callable[..., Any],
    *,
    profile: profiles.ProfileLike | None = None,
) -> Any:
    r"""Run an experiment callable inside a Cherries profile.

    Missing positional and keyword arguments are built from their annotations
    when possible. Pydantic models are logged as parameters before the callable
    runs. Coroutine results are awaited with `asyncio.run()`.

    Args:
        main: Experiment callable.
        profile: Profile name, profile instance, or profile class.

    Returns:
        The callable result. If the callable returns a coroutine, Cherries waits
        for it with `asyncio.run()` and returns the awaited value.

    Raises:
        BaseException: Re-raises any exception from the experiment after ending
            the run with the captured exception.

    Examples:
        Use a typed config object and a queued output path in an experiment:

        ```python
        from pathlib import Path

        from liblaf import cherries


        class Config(cherries.BaseConfig):
            name: str = "world"
            output: Path = cherries.output("hello.txt", mkdir=True)


        def experiment(cfg: Config) -> None:
            cfg.output.write_text(f"Hello, {cfg.name}!\\n")
            cherries.log_metric("message_length", len(cfg.name))


        cherries.main(experiment, profile="debug")
        ```
    """
    run: core.Run = start(profile=profile)
    args, kwargs = _make_args(main)
    configs: list[pydantic.BaseModel] = [
        arg for arg in (*args, *kwargs.values()) if isinstance(arg, pydantic.BaseModel)
    ]
    for config in configs:
        run.log_params(config.model_dump(mode="json"))
    try:
        result: Any = main(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result: Any = asyncio.run(result)
    except BaseException as exc:
        run.end(exc=exc)
        raise
    else:
        run.end()
        return result


def _make_args(func: Callable) -> tuple[Sequence[Any], Mapping[str, Any]]:
    """Build call arguments for `func` from defaults and annotations."""
    signature: inspect.Signature = inspect.signature(func, eval_str=True)
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        match param.kind:
            case Parameter.POSITIONAL_ONLY:
                args.append(_make_arg(param))
            case Parameter.POSITIONAL_OR_KEYWORD | Parameter.KEYWORD_ONLY:
                kwargs[name] = _make_arg(param)
            case _:
                pass
    return args, kwargs


def _make_arg(param: Parameter) -> Any:
    """Build one argument value for a function parameter."""
    if param.default is not Parameter.empty:
        return param.default
    if param.annotation is not Parameter.empty and not isinstance(
        param.annotation, str
    ):
        return param.annotation()
    return None

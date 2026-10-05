# Copyright (c) 2026 liblaf
import asyncio
import contextlib
import inspect
import sys
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from inspect import Parameter
from pathlib import Path
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


        def experiment(cfg: Config) -> None:
            output = cherries.output("hello.txt")
            output.write_text(f"Hello, {cfg.name}!\\n")
            cherries.log_metric("message_length", len(cfg.name))


        cherries.main(experiment, profile="debug")
        ```
    """
    # CLI help and invalid configuration must exit before creating work or
    # recording a successful SystemExit(0) as an experiment.
    args, kwargs = _make_args(main)
    run: core.Run = start(profile=profile)
    try:
        with _capture_stdio(run):
            configs: list[pydantic.BaseModel] = [
                arg
                for arg in (*args, *kwargs.values())
                if isinstance(arg, pydantic.BaseModel)
            ]
            original_configs = [config.model_dump(mode="json") for config in configs]
            for value in original_configs:
                run.log_params(value)
            result: Any = main(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            for config, original in zip(configs, original_configs, strict=True):
                resolved = config.model_dump(mode="json")
                if resolved != original:
                    run.log_params(resolved)
    except BaseException as exc:
        run.end(exc=exc)
        raise
    else:
        run.end()
        return result


class _Tee:
    def __init__(self, original: Any, stream: Any) -> None:
        self.original = original
        self.stream = stream

    def write(self, text: str) -> int:
        self.original.write(text)
        return self.stream.write(text)

    def flush(self) -> None:
        self.original.flush()
        self.stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original, name)


@contextlib.contextmanager
def _capture_stdio(run: core.Run) -> Iterator[None]:
    if not getattr(run, "active", False):
        yield
        return
    logs = Path(run.working_dir) / "logs"
    with (
        (logs / "stdout.log").open("w") as stdout,
        (logs / "stderr.log").open("w") as stderr,
        contextlib.redirect_stdout(_Tee(sys.stdout, stdout)),
        contextlib.redirect_stderr(_Tee(sys.stderr, stderr)),
    ):
        yield


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

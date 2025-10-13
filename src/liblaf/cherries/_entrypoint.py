import datetime
import inspect
import itertools
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pydantic

from liblaf.cherries import config as _config
from liblaf.cherries import core, profiles


def end(*args, **kwargs) -> None:
    core.active_run.log_other("cherries.end_time", datetime.datetime.now().astimezone())
    core.active_run.end(*args, **kwargs)


def run[T](main: Callable[..., T], *, profile: profiles.ProfileLike | None = None) -> T:
    run: core.Run = start(profile=profile)
    args: Sequence[Any]
    kwargs: Mapping[str, Any]
    args, kwargs = _make_args(main)
    configs: list[pydantic.BaseModel] = [
        arg
        for arg in itertools.chain(args, *kwargs.values())
        if isinstance(arg, pydantic.BaseModel)
    ]
    for config in configs:
        run.log_parameters(_config.model_dump_without_assets(config, mode="json"))
        for path in _config.get_inputs(config):
            run.log_input(path)
    try:
        return main(*args, **kwargs)
    finally:
        for config in configs:
            for path in _config.get_outputs(config):
                run.log_output(path)
        run.end()


def start(
    profile: profiles.ProfileLike | None = None,
) -> core.Run:
    run: core.Run = profiles.factory(profile).init()
    run.start()
    run.log_other("cherries.entrypoint", run.entrypoint.relative_to(run.project_dir))
    run.log_other("cherries.exp_dir", run.exp_dir.relative_to(run.project_dir))
    run.log_other("cherries.start_time", run.start_time)
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

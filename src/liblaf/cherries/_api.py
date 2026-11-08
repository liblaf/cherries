# Copyright (c) 2026 liblaf
"""Public experiment context and compatibility helpers."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

import pydantic

from . import core
from ._main import main as legacy_main
from ._main._main import _make_args
from .store._config import configured_project, settings
from .store._runtime import RunContext, current_run


def run(
    *,
    name: str | None = None,
    kind: str | None = None,
    parameters: dict[str, Any] | None = None,
    tags: tuple[str, ...] | list[str] = (),
    on_error: str | None = None,
    store: Any = None,
    project: Any = None,
    project_dir: Path | str | None = None,
) -> RunContext:
    selected = configured_project(project_dir, store=store, project=project)
    return RunContext(
        selected,
        name=name or Path(os.sys.argv[0]).stem,
        kind=kind,
        parameters=parameters,
        tags=tags,
        on_error=on_error,
    )


def dispatch(name: str, legacy: Callable) -> Callable:
    @wraps(legacy)
    def call(*args: Any, **kwargs: Any) -> Any:
        active = current_run()
        if active is None:
            return legacy(*args, **kwargs)
        target = "scratch" if name == "temp" else name
        return getattr(active, target)(*args, **kwargs)

    return call


def main(function: Callable, *, profile: Any = None) -> Any:
    """Run typed-config functions; legacy configurations keep their old format."""
    _, config = settings()
    if profile is not None or (
        not os.environ.get("CHERRIES_STORE")
        and not config.get("project", {}).get("id")
        and (os.environ.get("CHERRIES_STORAGE") or "collection" in config)
    ):
        return legacy_main(function, profile=profile)
    args, kwargs = _make_args(function)
    parameters = {}
    for value in (*args, *kwargs.values()):
        if isinstance(value, pydantic.BaseModel):
            parameters.update(value.model_dump(mode="json"))
    with run(name=function.__name__, parameters=parameters):
        result = function(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        return result


input = dispatch("input", core.input)  # noqa: A001 - public compatibility API
output = dispatch("output", core.output)
temp = dispatch("temp", core.temp)
log_metric = dispatch("log_metric", core.log_metric)
log_metrics = dispatch("log_metrics", core.log_metrics)
log_param = dispatch("log_param", core.log_param)
log_params = dispatch("log_params", core.log_params)
get_step = dispatch("get_step", core.get_step)
set_step = dispatch("set_step", core.set_step)
get_param = dispatch("get_param", core.get_param)
get_params = dispatch("get_params", core.get_params)
get_metric = dispatch("get_metric", core.get_metric)
get_metrics = dispatch("get_metrics", core.get_metrics)

"""Run Python experiments with typed config, path helpers, and plugins.

Cherries exposes a compact facade around a process-global
[`Run`][liblaf.cherries.core.Run]. Use [`main`][liblaf.cherries.main] to run an
experiment function inside a profile, [`BaseConfig`][liblaf.cherries.BaseConfig]
for typed settings, and helpers such as [`output`][liblaf.cherries.output] to
queue artifacts for logging at shutdown.
"""

from . import config, core, plugins, utils
from ._main import end, main, start
from ._version import __commit_id__, __version__, __version_tuple__
from .config import BaseConfig
from .core import (
    Run,
    get_metric,
    get_metrics,
    get_other,
    get_others,
    get_param,
    get_params,
    get_step,
    input,  # noqa: A004
    log_asset,
    log_input,
    log_metric,
    log_metrics,
    log_other,
    log_others,
    log_output,
    log_param,
    log_params,
    log_temp,
    output,
    run,
    set_step,
    temp,
)

__all__ = [
    "BaseConfig",
    "Run",
    "__commit_id__",
    "__version__",
    "__version_tuple__",
    "config",
    "core",
    "end",
    "get_metric",
    "get_metrics",
    "get_other",
    "get_others",
    "get_param",
    "get_params",
    "get_step",
    "input",
    "log_asset",
    "log_input",
    "log_metric",
    "log_metrics",
    "log_other",
    "log_others",
    "log_output",
    "log_param",
    "log_params",
    "log_temp",
    "main",
    "output",
    "plugins",
    "run",
    "set_step",
    "start",
    "temp",
    "utils",
]

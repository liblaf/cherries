# Copyright (c) 2026 liblaf
"""Record experiments in shared project/run filesystem stores.

Use ``with cherries.run(...)`` for explicit recording, ``Store`` to inspect
saved runs, and ``FileRef`` to pin inputs. The previous collection recorder is
available through ``liblaf.cherries.legacy``.
"""

from . import config, core, plugins, utils
from ._access import RunAccessor, open_run
from ._api import (
    get_metric,
    get_metrics,
    get_param,
    get_params,
    get_step,
    input,  # noqa: A004 - public API
    log_metric,
    log_metrics,
    log_param,
    log_params,
    main,
    output,
    run,
    set_step,
    temp,
)
from ._main import end, start
from ._version import __commit_id__, __version__, __version_tuple__
from .config import BaseConfig
from .core import (
    Run as LegacyRun,
)
from .core import (
    get_other,
    get_others,
    log_asset,
    log_input,
    log_other,
    log_others,
    log_output,
    log_temp,
)
from .store import (
    ConflictError,
    DirectoryRef,
    DraftRun,
    FileRef,
    IntegrityError,
    NotFoundError,
    Project,
    Run,
    RunContext,
    RunFile,
    RunResult,
    Store,
    StoreError,
)

__all__ = [
    "BaseConfig",
    "ConflictError",
    "DirectoryRef",
    "DraftRun",
    "FileRef",
    "IntegrityError",
    "LegacyRun",
    "NotFoundError",
    "Project",
    "Run",
    "RunAccessor",
    "RunContext",
    "RunFile",
    "RunResult",
    "Store",
    "StoreError",
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
    "open_run",
    "output",
    "plugins",
    "run",
    "set_step",
    "start",
    "temp",
    "utils",
]

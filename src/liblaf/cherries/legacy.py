# Copyright (c) 2026 liblaf
"""Explicit compatibility access to the v4 immutable collection recorder."""

from ._access import RunAccessor, open_run
from ._main import end, main, start
from .core import (
    Run,
    input,  # noqa: A004 - compatibility export
    log_metric,
    log_metrics,
    output,
    run,
    temp,
)
from .records import Store

__all__ = [
    "Run",
    "RunAccessor",
    "Store",
    "end",
    "input",
    "log_metric",
    "log_metrics",
    "main",
    "open_run",
    "output",
    "run",
    "start",
    "temp",
]

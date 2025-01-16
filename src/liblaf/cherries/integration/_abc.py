from __future__ import annotations

import datetime
import functools
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Generic, TypeVar

from loguru import logger

from liblaf import cherries

_T = TypeVar("_T")


class Run(Generic[_T]):
    enabled: bool = True
    plugins: list[cherries.Plugin]
    _backend: _T

    def __init__(
        self,
        plugins: Sequence[cherries.Plugin] | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        if plugins is None:
            plugins = cherries.default_plugins()
        self.plugins = sorted(plugins, key=lambda plugin: plugin.priority)
        self.enabled = enabled
        set_current_run(self)
        if self.enabled:
            self.start()

    @property
    def backend(self) -> str:
        return "dummy"

    @property
    def id(self) -> str:
        raise NotImplementedError

    @functools.cached_property
    def creation_time(self) -> datetime.datetime:
        return datetime.datetime.now().astimezone()

    @functools.cached_property
    def entrypoint(self) -> Path:
        return Path(sys.argv[0]).absolute()

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def url(self) -> str:
        raise NotImplementedError

    def start(self) -> None:
        for plugin in self.plugins:
            plugin.pre_start()
        self._backend = self._start()
        for plugin in self.plugins:
            plugin.post_start(self)
        self.log_other("cherries/creation_time", self.creation_time)

    def end(self) -> None:
        for plugin in reversed(self.plugins):
            plugin.pre_end(self)
        self._end()
        for plugin in reversed(self.plugins):
            plugin.post_end(self)

    def log_metric(
        self,
        key: str,
        value: float,
        *,
        step: float | None = None,
        timestamp: float | None = None,
        **kwargs,
    ) -> None:
        logger.opt(depth=1).debug("{}: {}", key, value)
        if self.enabled:
            self._log_metric(key, value, step=step, timestamp=timestamp, **kwargs)

    def log_other(
        self,
        key: str,
        value: bool | float | str | datetime.datetime,
        **kwargs,
    ) -> None:
        logger.opt(depth=1).info("{}: {}", key, value)
        if self.enabled:
            self._log_other(key, value, **kwargs)

    def upload_file(self, key: str, path: str | os.PathLike[str], **kwargs) -> None:
        path = Path(path)
        logger.opt(depth=1).info("Uploading file: {}", path)
        if self.enabled:
            self._upload_file(key, path, **kwargs)

    def _start(self) -> _T: ...
    def _end(self) -> None: ...
    def _log_metric(
        self,
        key: str,
        value: float,
        *,
        step: float | None = None,
        timestamp: float | None = None,
        **kwargs,
    ) -> None: ...
    def _log_other(
        self, key: str, value: bool | float | str | datetime.datetime, **kwargs
    ) -> None: ...
    def _upload_file(self, key: str, path: Path, **kwargs) -> None: ...


_current_run: Run | None = None


def current_run() -> Run:
    global _current_run  # noqa: PLW0603
    if _current_run is None:
        _current_run = Run()
    return _current_run


def set_current_run(run: Run) -> None:
    global _current_run  # noqa: PLW0603
    _current_run = run

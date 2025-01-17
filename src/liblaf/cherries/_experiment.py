import atexit
import dataclasses
import datetime
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from environs import env
from loguru import logger

from liblaf import cherries


@dataclasses.dataclass(kw_only=True)
class Experiment:
    backend: cherries.Backend = dataclasses.field(
        default_factory=cherries.backend_factory
    )
    enabled: bool = dataclasses.field(
        default_factory=lambda: env.bool("LIBLAF_CHERRIES_ENABLED", True)
    )
    plugins: Sequence[cherries.Plugin] = dataclasses.field(
        default_factory=cherries.default_plugins
    )

    @property
    def entrypoint(self) -> Path:
        return self.backend.entrypoint

    @property
    def id(self) -> str:
        return self.backend.id

    @property
    def name(self) -> str:
        return self.backend.name

    @property
    def start_time(self) -> datetime.datetime:
        return self.backend.start_time

    @property
    def url(self) -> str:
        return self.backend.url

    def start(self) -> None:
        if not self.enabled:
            return
        self.plugins = sorted(self.plugins, key=lambda plugin: plugin.priority)
        for plugin in self.plugins:
            plugin.pre_start()
        self.backend.start()
        cherries.set_current_experiment(self)
        for plugin in self.plugins:
            plugin.post_start(self)
        self.log_other("cherries/entrypoint", self.entrypoint)
        self.log_other("cherries/start_time", self.start_time)
        atexit.register(self.end)

    def end(self) -> None:
        if not self.enabled:
            return
        for plugin in reversed(self.plugins):
            plugin.pre_end(self)
        self.backend.end()
        for plugin in reversed(self.plugins):
            plugin.post_end(self)
        self.enabled = False  # prevent `end()` from being called multiple times

    def log_metric(
        self,
        key: str,
        value: float,
        *,
        step: float | None = None,
        timestamp: float | None = None,
        **kwargs,
    ) -> None:
        if not self.enabled:
            return
        logger.opt(depth=1).debug("{}: {}", key, value)
        self.backend.log_metric(key, value, step=step, timestamp=timestamp, **kwargs)

    def log_other(self, key: str, value: Any, **kwargs) -> None:
        if not self.enabled:
            return
        logger.opt(depth=1).info("{}: {}", key, value)
        self.backend.log_other(key, value, **kwargs)

    def upload_file(self, key: str, path: str | os.PathLike[str], **kwargs) -> None:
        if not self.enabled:
            return
        path = Path(path)
        logger.opt(depth=1).info("Uploading file: {}", path)
        self.backend.upload_file(key, path, **kwargs)


_current_experiment: Experiment | None = None


def current_experiment() -> Experiment:
    global _current_experiment  # noqa: PLW0603
    if _current_experiment is None:
        _current_experiment = Experiment()
    return _current_experiment


def set_current_experiment(experiment: Experiment) -> None:
    global _current_experiment  # noqa: PLW0603
    _current_experiment = experiment

import datetime
import functools
from pathlib import Path
from typing import Any

import pydantic_settings as ps

from liblaf import cherries


class Backend(ps.BaseSettings):
    model_config = ps.SettingsConfigDict(
        frozen=True, env_prefix=cherries.ENV_PREFIX + "DUMMY_"
    )
    enabled: bool = True

    @property
    def backend(self) -> str:
        return "dummy"

    @functools.cached_property
    def entrypoint(self) -> Path:
        return cherries.entrypoint()

    @property
    def id(self) -> str:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    @functools.cached_property
    def start_time(self) -> datetime.datetime:
        return datetime.datetime.now().astimezone()

    @property
    def url(self) -> str:
        raise NotImplementedError

    def start(self) -> None: ...
    def end(self) -> None: ...
    def log_metric(
        self,
        key: str,
        value: float,
        *,
        step: float | None = None,
        timestamp: float | None = None,
        **kwargs,
    ) -> None: ...
    def log_other(self, key: str, value: Any, **kwargs) -> None: ...
    def upload_file(self, key: str, path: Path, **kwargs) -> None: ...

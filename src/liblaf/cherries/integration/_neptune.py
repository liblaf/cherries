import datetime
from pathlib import Path

import neptune
import neptune.common.exceptions
import pydantic
import pydantic_settings as ps

from liblaf import cherries


class BackendNeptune(cherries.Backend):
    model_config = ps.SettingsConfigDict(
        frozen=True, env_prefix=cherries.ENV_PREFIX + "NEPTUNE_"
    )
    _backend: neptune.Run = pydantic.PrivateAttr()

    @property
    def backend(self) -> str:
        return "neptune"

    @property
    def id(self) -> str:
        return self._backend["sys/id"].fetch()

    @property
    def name(self) -> str:
        return self._backend["sys/name"].fetch()

    @property
    def url(self) -> str:
        return self._backend.get_url()

    def start(self) -> None:
        self._backend = neptune.init_run()

    def end(self) -> None:
        self._backend.stop()

    def log_metric(
        self,
        key: str,
        value: float,
        *,
        step: float | None = None,
        timestamp: float | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        self._backend[key].append(value, step=step, timestamp=timestamp)

    def log_other(
        self,
        key: str,
        value: bool | float | str | datetime.datetime,
        **kwargs,  # noqa: ARG002
    ) -> None:
        self._backend[key] = value

    def upload_file(self, key: str, path: Path, **kwargs) -> None:
        return self._backend[key].upload(path, **kwargs)

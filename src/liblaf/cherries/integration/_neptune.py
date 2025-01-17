import os
from pathlib import Path
from typing import Any

import neptune
import neptune.common.exceptions
import neptune.utils
import pydantic
import pydantic_settings as ps

from liblaf import cherries


class BackendNeptune(cherries.Backend):
    model_config = ps.SettingsConfigDict(frozen=True, env_prefix="NEPTUNE_")
    monitoring_namespace: str | None = None
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
        neptune.common.exceptions.STYLES.update(neptune.common.exceptions.EMPTY_STYLES)
        self._backend = neptune.init_run(monitoring_namespace=self.monitoring_namespace)

    def end(self) -> None:
        self._backend.stop()

    def log_metric(
        self,
        key: str,
        value: float,
        *,
        step: float | None = None,
        timestamp: float | None = None,
        **kwargs,
    ) -> None:
        self._backend[key].append(value, step=step, timestamp=timestamp, **kwargs)

    def log_other(self, key: str, value: Any, **kwargs) -> None:
        value = stringify_unsupported(value)
        self._backend[key].assign(value, **kwargs)

    def upload_file(self, key: str, path: Path, **kwargs) -> None:
        return self._backend[key].upload(str(path), **kwargs)


def stringify_unsupported(value: Any) -> Any:
    if isinstance(value, pydantic.BaseModel):
        return value.model_dump()
    if isinstance(value, os.PathLike):
        return str(value)
    return value

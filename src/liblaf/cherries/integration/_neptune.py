import datetime

import neptune
import neptune.common.exceptions

from liblaf import cherries


class RunNeptune(cherries.Run[neptune.Run]):
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

    def _start(self) -> neptune.Run:
        return neptune.init_run()

    def _end(self) -> None:
        return self._backend.stop()

    def _log_metric(
        self,
        key: str,
        value: float,
        *,
        step: float | None = None,
        timestamp: float | None = None,
    ) -> None:
        self._backend[key].append(value, step=step, timestamp=timestamp)

    def _log_other(
        self, key: str, value: bool | float | str | datetime.datetime
    ) -> None:
        self._backend[key] = value

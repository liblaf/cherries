import datetime
from typing import Protocol


class MetricPluginProtocol(Protocol):
    def log_metric(
        self, name: str, value: float, *, step: int, time: datetime.datetime
    ) -> None: ...

    def log_metrics(
        self, metrics: dict[str, float], *, step: int, time: datetime.datetime
    ) -> None: ...

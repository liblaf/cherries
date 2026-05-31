import datetime
from collections.abc import Mapping
from typing import Protocol, SupportsFloat

type MetricsLike = Mapping[str, SupportsFloat | MetricsLike]


class MetricPluginProtocol(Protocol):
    def log_metric(
        self, name: str, value: float, *, step: int, time: datetime.datetime
    ) -> None: ...

    def log_metrics(
        self, metrics: dict[str, float], *, step: int, time: datetime.datetime
    ) -> None: ...

import datetime
from collections.abc import Mapping
from typing import Protocol, SupportsFloat

type MetricsLike = Mapping[str, SupportsFloat | MetricsLike]
"""Nested mapping accepted by batch metric logging."""


class MetricPluginProtocol(Protocol):
    """Hook surface for plugins that receive scalar metrics."""

    def log_metric(
        self, name: str, value: float, *, step: int, time: datetime.datetime
    ) -> None:
        """Record one metric sample."""
        ...

    def log_metrics(
        self, metrics: dict[str, float], *, step: int, time: datetime.datetime
    ) -> None:
        """Record a batch of already-flattened metric samples."""
        ...

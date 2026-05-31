from collections.abc import Iterable
from datetime import datetime
from typing import SupportsFloat, SupportsInt

import attrs
import polars as pl

from liblaf.cherries.utils import flatten_dict

from ._protocol import MetricPluginProtocol, MetricsLike
from ._struct import Metric


@attrs.define
class MetricsManager:
    plugins: MetricPluginProtocol
    metrics: dict[str, Metric] = attrs.field(factory=dict)
    step: int = 0

    def get_metric(self, name: str) -> pl.DataFrame:
        return self.metrics[name].to_polars()

    def get_metrics(self, names: Iterable[str] | None = None) -> pl.DataFrame:
        if names is None:
            names: Iterable[str] = self.metrics.keys()
        return pl.concat(
            [self.metrics[name].to_polars() for name in names], how="vertical"
        )

    def log_metric(
        self,
        name: str,
        value: SupportsFloat,
        *,
        step: SupportsInt | None = None,
        time: datetime | None = None,
    ) -> None:
        step, time = self._parse_inputs(step, time)
        value: float = float(value)
        self._append_metric(name, value, step=step, time=time)
        self.plugins.log_metric(name, value, step=step, time=time)

    def log_metrics(
        self,
        metrics: MetricsLike,
        *,
        step: SupportsInt | None = None,
        time: datetime | None = None,
    ) -> None:
        step, time = self._parse_inputs(step, time)
        flat: dict[str, SupportsFloat] = flatten_dict(metrics)
        flat: dict[str, float] = {name: float(value) for name, value in flat.items()}
        for name, value in flat.items():
            self._append_metric(name, value, step=step, time=time)
        self.plugins.log_metrics(flat, step=step, time=time)

    def _append_metric(
        self, name: str, value: float, *, step: int, time: datetime
    ) -> None:
        if name not in self.metrics:
            self.metrics[name] = Metric(name=name)
        self.metrics[name].append(value, step, time)

    def _parse_inputs(
        self, step: SupportsInt | None, time: datetime | None
    ) -> tuple[int, datetime]:
        if time is None:
            time: datetime = datetime.now()  # noqa: DTZ005
        if step is None:
            step: int = self.step
        else:
            step: int = int(step)
        return step, time

import datetime
from collections.abc import Iterable, Mapping
from typing import Any, SupportsFloat, SupportsInt

import attrs
import polars as pl

from ._protocol import MetricPluginProtocol
from ._struct import Metric


@attrs.define
class MetricsManager:
    plugins: MetricPluginProtocol
    metrics: dict[str, Metric] = attrs.field(factory=dict)
    step: int = 0

    def get_metric(self, name: str) -> pl.DataFrame:
        return self.metrics[name].to_polars()

    def get_metrics(self, names: Iterable[str]) -> pl.DataFrame:
        return pl.concat(
            [self.metrics[name].to_polars() for name in names], how="vertical"
        )

    def log_metric(
        self,
        name: str,
        value: SupportsFloat,
        *,
        step: SupportsInt | None = None,
        time: datetime.datetime | None = None,
    ) -> None:
        step, time = self._parse_inputs(step, time)
        value: float = float(value)
        self._append_metric(name, value, step=step, time=time)
        self.plugins.log_metric(name, value, step=step, time=time)

    def log_metrics(
        self,
        metrics: Mapping[str, Any],
        *,
        step: SupportsInt | None = None,
        time: datetime.datetime | None = None,
    ) -> None:
        step, time = self._parse_inputs(step, time)
        flat: dict[str, float] = _flatten_mapping(metrics)
        for name, value in flat.items():
            self._append_metric(name, value, step=step, time=time)
        self.plugins.log_metrics(flat, step=step, time=time)

    def _append_metric(
        self, name: str, value: float, *, step: int, time: datetime.datetime
    ) -> None:
        if name not in self.metrics:
            self.metrics[name] = Metric(name=name)
        self.metrics[name].append(value, step, time)

    def _parse_inputs(
        self, step: SupportsInt | None, time: datetime.datetime | None
    ) -> tuple[int, datetime.datetime]:
        if time is None:
            time: datetime.datetime = datetime.datetime.now()  # noqa: DTZ005
        if step is None:
            step: int = self.step
        else:
            step: int = int(step)
        return step, time


def _flatten_mapping(mapping: Mapping[str, Any], prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in mapping.items():
        key_flat: str = f"{prefix}/{key}" if prefix else key
        if isinstance(value, Mapping):
            result.update(_flatten_mapping(value, key_flat))
        else:
            result[key_flat] = float(value)
    return result

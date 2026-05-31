import datetime
from datetime import UTC
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import polars as pl

from liblaf.cherries.core.metrics import MetricsManager


def test_metric_time_is_stored_as_utc_epoch_milliseconds() -> None:
    time = datetime.datetime(2026, 5, 31, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    plugins = Mock()
    metrics = MetricsManager(plugins=plugins)

    metrics.log_metric("loss", 1, time=time)
    df = metrics.get_metric("loss")

    assert df.schema == {
        "name": pl.String,
        "value": pl.Float64,
        "step": pl.UInt64,
        "time": pl.Datetime("ms"),
    }
    assert df.item(0, "time") == datetime.datetime(
        2026, 5, 31, 13, 30, tzinfo=UTC
    ).replace(tzinfo=None)
    plugins.log_metric.assert_called_once_with("loss", 1.0, step=0, time=time)


def test_log_metrics_flattens_nested_mappings_and_uses_explicit_step() -> None:
    time = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    plugins = Mock()
    metrics = MetricsManager(plugins=plugins)

    metrics.log_metrics({"train": {"loss": 0.5}, "accuracy": 0.75}, step=4, time=time)
    df = metrics.get_metrics(("train/loss", "accuracy")).sort("name")

    assert df["name"].to_list() == ["accuracy", "train/loss"]
    assert df["value"].to_list() == [0.75, 0.5]
    assert df["step"].to_list() == [4, 4]
    plugins.log_metrics.assert_called_once_with(
        {"train/loss": 0.5, "accuracy": 0.75}, step=4, time=time
    )

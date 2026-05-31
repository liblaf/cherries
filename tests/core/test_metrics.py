import datetime
from zoneinfo import ZoneInfo

import polars as pl

from liblaf.cherries.core._metrics import MetricsManager


def test_metric_uses_utc_for_fixed_offset_time_zone() -> None:
    time = datetime.datetime(
        2026,
        5,
        31,
        21,
        30,
        tzinfo=datetime.timezone(datetime.timedelta(hours=8), "CST"),
    )
    metrics = MetricsManager()

    metrics.log_metric("x", 1, time=time)
    df = metrics.get_metric("x")

    assert df.schema["timestamp"] == pl.Datetime("us", "UTC")
    assert df.item(0, "timestamp") == datetime.datetime(
        2026, 5, 31, 13, 30, tzinfo=datetime.UTC
    )


def test_metric_preserves_zoneinfo_time_zone() -> None:
    time = datetime.datetime(2026, 5, 31, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    metrics = MetricsManager()

    metrics.log_metric("x", 1, time=time)
    df = metrics.get_metric("x")

    assert df.schema["timestamp"] == pl.Datetime("us", "Asia/Shanghai")
    assert df.item(0, "timestamp") == time

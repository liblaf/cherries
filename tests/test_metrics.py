from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from liblaf.cherries.core.metrics import MetricsManager


class RecordingMetricsPlugin:
    def __init__(self) -> None:
        self.metric_calls: list[tuple[str, float, int, datetime]] = []
        self.metrics_calls: list[tuple[dict[str, float], int, datetime]] = []

    def log_metric(self, name: str, value: float, *, step: int, time: datetime) -> None:
        self.metric_calls.append((name, value, step, time))

    def log_metrics(
        self, metrics: dict[str, float], *, step: int, time: datetime
    ) -> None:
        self.metrics_calls.append((metrics, step, time))


def test_log_metric_records_dataframe_row_and_plugin_call() -> None:
    plugin = RecordingMetricsPlugin()
    manager = MetricsManager(plugins=plugin)
    when = datetime(2026, 1, 2, 3, 4, 5, 123000, tzinfo=UTC)
    expected_time = when.replace(tzinfo=None)
    manager.step = 7

    manager.log_metric("loss", 0.25, time=when)
    row = manager.get_metric("loss").row(0, named=True)

    assert row == {
        "name": "loss",
        "value": 0.25,
        "step": 7,
        "time": expected_time,
    }
    assert plugin.metric_calls == [("loss", 0.25, 7, when)]


def test_log_metrics_flattens_nested_mappings_once_per_batch() -> None:
    plugin = RecordingMetricsPlugin()
    manager = MetricsManager(plugins=plugin)
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    expected_time = when.replace(tzinfo=None)

    manager.log_metrics(
        {"train": {"loss": 0.5}, "valid": {"accuracy": 0.75}},
        step=2,
        time=when,
    )

    rows = manager.get_metrics(["train/loss", "valid/accuracy"]).to_dicts()
    assert rows == [
        {
            "name": "train/loss",
            "value": 0.5,
            "step": 2,
            "time": expected_time,
        },
        {
            "name": "valid/accuracy",
            "value": 0.75,
            "step": 2,
            "time": expected_time,
        },
    ]
    assert plugin.metrics_calls == [
        ({"train/loss": 0.5, "valid/accuracy": 0.75}, 2, when)
    ]


def test_metric_timestamps_accept_fixed_offset_timezone_names() -> None:
    plugin = RecordingMetricsPlugin()
    manager = MetricsManager(plugins=plugin)
    cst = timezone(timedelta(hours=8), "CST")
    when = datetime(2026, 1, 2, 3, 4, 5, 123000, tzinfo=cst)

    manager.log_metric("loss", 1.5, time=when)
    row = manager.get_metric("loss").row(0, named=True)

    assert row == {
        "name": "loss",
        "value": 1.5,
        "step": 0,
        "time": when.astimezone(UTC).replace(tzinfo=None),
    }
    assert plugin.metric_calls == [("loss", 1.5, 0, when)]


def test_get_metrics_without_names_returns_all_series() -> None:
    plugin = RecordingMetricsPlugin()
    manager = MetricsManager(plugins=plugin)
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    manager.log_metric("train/loss", 0.4, step=1, time=when)
    manager.log_metric("valid/loss", 0.5, step=1, time=when)

    assert manager.get_metrics().select("name", "value").to_dicts() == [
        {"name": "train/loss", "value": 0.4},
        {"name": "valid/loss", "value": 0.5},
    ]

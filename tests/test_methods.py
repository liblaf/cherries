from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from liblaf.cherries.core import Run
from liblaf.cherries.core import _methods as methods


class RecordingRun:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.metric = pl.DataFrame({"name": ["loss"], "value": [0.25]})
        self.metrics = pl.DataFrame({"name": ["loss"], "value": [0.25]})

    def start(self) -> None:
        self.calls.append(("start", (), {}))

    def end(self, exc: BaseException | None = None) -> None:
        self.calls.append(("end", (), {"exc": exc}))

    def get_step(self) -> int:
        self.calls.append(("get_step", (), {}))
        return 7

    def set_step(self, step: int) -> None:
        self.calls.append(("set_step", (step,), {}))

    def get_metric(self, name: str) -> pl.DataFrame:
        self.calls.append(("get_metric", (name,), {}))
        return self.metric

    def log_metric(
        self,
        name: str,
        value: float,
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        self.calls.append(("log_metric", (name, value), {"step": step, "time": time}))

    def get_metrics(self, metrics: Iterator[str] | None = None) -> pl.DataFrame:
        self.calls.append(("get_metrics", (metrics,), {}))
        return self.metrics

    def log_metrics(
        self,
        metrics: dict[str, float],
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        self.calls.append(("log_metrics", (metrics,), {"step": step, "time": time}))

    def input(self, path: str, *, metadata: dict[str, Any] | None = None) -> Path:
        self.calls.append(("input", (path,), {"metadata": metadata}))
        return Path("data") / path

    def output(
        self,
        path: str,
        *,
        metadata: dict[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        self.calls.append(("output", (path,), {"metadata": metadata, "mkdir": mkdir}))
        return Path("data") / path

    def temp(
        self,
        path: str,
        *,
        metadata: dict[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        self.calls.append(("temp", (path,), {"metadata": metadata, "mkdir": mkdir}))
        return Path("tmp") / path

    def log_asset(self, path: str, metadata: dict[str, Any] | None = None) -> None:
        self.calls.append(("log_asset", (path,), {"metadata": metadata}))

    def log_input(self, path: str, metadata: dict[str, Any] | None = None) -> None:
        self.calls.append(("log_input", (path,), {"metadata": metadata}))

    def log_output(self, path: str, metadata: dict[str, Any] | None = None) -> None:
        self.calls.append(("log_output", (path,), {"metadata": metadata}))

    def log_temp(self, path: str, metadata: dict[str, Any] | None = None) -> None:
        self.calls.append(("log_temp", (path,), {"metadata": metadata}))

    def get_other(self, name: str) -> Any:
        self.calls.append(("get_other", (name,), {}))
        return "value"

    def log_other(self, name: str, value: Any) -> None:
        self.calls.append(("log_other", (name, value), {}))

    def get_others(self) -> dict[str, Any]:
        self.calls.append(("get_others", (), {}))
        return {"host": "worker"}

    def log_others(self, others: dict[str, Any]) -> None:
        self.calls.append(("log_others", (others,), {}))

    def get_param(self, name: str) -> Any:
        self.calls.append(("get_param", (name,), {}))
        return 3

    def log_param(self, name: str, value: Any) -> None:
        self.calls.append(("log_param", (name, value), {}))

    def get_params(self) -> dict[str, Any]:
        self.calls.append(("get_params", (), {}))
        return {"epochs": 3}

    def log_params(self, params: dict[str, Any]) -> None:
        self.calls.append(("log_params", (params,), {}))


def test_public_methods_forward_to_process_global_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = RecordingRun()
    monkeypatch.setattr(methods, "run", cast("Run", run))
    when = datetime(2026, 6, 1, 12, 30, tzinfo=UTC)
    exc = RuntimeError("boom")

    methods.start()
    methods.end(exc)
    assert methods.get_step() == 7
    methods.set_step(8)
    assert methods.get_metric("loss") is run.metric
    methods.log_metric("loss", 0.25, step=2, time=when)
    metrics = iter(["loss"])
    assert methods.get_metrics(metrics) is run.metrics
    methods.log_metrics({"loss": 0.25}, step=2, time=when)
    assert methods.input("raw.txt", metadata={"split": "train"}) == Path("data/raw.txt")
    assert methods.output("out.txt", mkdir=False) == Path("data/out.txt")
    assert methods.temp("cache.bin") == Path("tmp/cache.bin")
    methods.log_asset("plot.png")
    methods.log_input("raw.txt")
    methods.log_output("out.txt")
    methods.log_temp("cache.bin")
    assert methods.get_other("host") == "value"
    methods.log_other("host", "worker")
    assert methods.get_others() == {"host": "worker"}
    methods.log_others({"host": "worker"})
    assert methods.get_param("epochs") == 3
    methods.log_param("epochs", 3)
    assert methods.get_params() == {"epochs": 3}
    methods.log_params({"epochs": 3})

    assert run.calls == [
        ("start", (), {}),
        ("end", (), {"exc": exc}),
        ("get_step", (), {}),
        ("set_step", (8,), {}),
        ("get_metric", ("loss",), {}),
        ("log_metric", ("loss", 0.25), {"step": 2, "time": when}),
        ("get_metrics", (metrics,), {}),
        ("log_metrics", ({"loss": 0.25},), {"step": 2, "time": when}),
        ("input", ("raw.txt",), {"metadata": {"split": "train"}}),
        ("output", ("out.txt",), {"metadata": None, "mkdir": False}),
        ("temp", ("cache.bin",), {"metadata": None, "mkdir": True}),
        ("log_asset", ("plot.png",), {"metadata": None}),
        ("log_input", ("raw.txt",), {"metadata": None}),
        ("log_output", ("out.txt",), {"metadata": None}),
        ("log_temp", ("cache.bin",), {"metadata": None}),
        ("get_other", ("host",), {}),
        ("log_other", ("host", "worker"), {}),
        ("get_others", (), {}),
        ("log_others", ({"host": "worker"},), {}),
        ("get_param", ("epochs",), {}),
        ("log_param", ("epochs", 3), {}),
        ("get_params", (), {}),
        ("log_params", ({"epochs": 3},), {}),
    ]

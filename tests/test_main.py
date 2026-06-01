from __future__ import annotations

from typing import Any, cast

import pydantic
import pytest

from liblaf import cherries
from liblaf.cherries import core
from liblaf.cherries.profiles import Profile


class Config(pydantic.BaseModel):
    value: int = 3


class RecordingRun:
    def __init__(self) -> None:
        self.started = False
        self.ended_with: list[BaseException | None] = []
        self.params: list[dict[str, Any]] = []

    def start(self) -> None:
        self.started = True

    def end(self, exc: BaseException | None = None) -> None:
        self.ended_with.append(exc)

    def log_params(self, params: dict[str, Any]) -> None:
        self.params.append(params)


class ProfileForTest(Profile):
    def __init__(self, run: RecordingRun) -> None:
        self.run = run

    def init(self) -> core.Run:
        return cast("core.Run", self.run)


def test_main_builds_annotated_config_logs_params_and_returns_result() -> None:
    run = RecordingRun()

    def experiment(cfg: Config, label: str = "ok") -> str:
        assert isinstance(cfg, Config)
        return f"{cfg.value}:{label}"

    result = cherries.main(experiment, profile=ProfileForTest(run))

    assert result == "3:ok"
    assert run.started is True
    assert run.ended_with == [None]
    assert run.params == [{"value": 3}]


def test_main_awaits_coroutine_results() -> None:
    run = RecordingRun()

    async def experiment() -> int:
        return 7

    assert cherries.main(experiment, profile=ProfileForTest(run)) == 7
    assert run.ended_with == [None]


def test_main_ends_run_with_exception_then_reraises() -> None:
    run = RecordingRun()
    message = "failed"

    def experiment() -> None:
        raise ValueError(message)

    with pytest.raises(ValueError, match=message):
        cherries.main(experiment, profile=ProfileForTest(run))

    assert len(run.ended_with) == 1
    assert isinstance(run.ended_with[0], ValueError)

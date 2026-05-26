import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import attrs
import pydantic
import pytest

from liblaf import cherries
from liblaf.cherries import core, profiles

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class RunRecorder(core.Plugin):
    params: list[dict[str, Any]] = attrs.field(factory=list)
    ended: list[BaseException | None] = attrs.field(factory=list)
    others: dict[str, Any] = attrs.field(factory=dict)

    @core.impl
    def log_other(self, name: str, value: Any) -> None:
        self.others[name] = value

    @core.impl
    def log_params(self, params: dict[str, Any]) -> None:
        self.params.append(dict(params))

    @core.impl
    def end(
        self,
        *_args: Any,
        exc: BaseException | None = None,
        **_kwargs: Any,
    ) -> None:
        self.ended.append(exc)


class ProfileForTest(profiles.Profile):
    def __init__(self, run: core.Run) -> None:
        self.run = run

    def init(self) -> core.Run:
        return self.run


def make_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[core.Run, RunRecorder]:
    run = core.Run()
    monkeypatch.setattr(run, "entrypoint", tmp_path / "experiment.py")
    monkeypatch.setattr(run, "exp_dir", tmp_path)
    monkeypatch.setattr(run, "project_dir", tmp_path)
    recorder = RunRecorder()
    run.register(recorder)
    return run, recorder


def test_main_builds_annotated_arguments_and_logs_pydantic_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run, recorder = make_run(monkeypatch, tmp_path)

    class Token:
        pass

    class Config(pydantic.BaseModel):
        name: str = "Ada"

    def experiment(
        token: Token,
        /,
        cfg: Config,
        count: int = 2,
        *,
        note: str | None = None,
        **extra: Any,
    ) -> str:
        assert isinstance(token, Token)
        assert cfg.name == "Ada"
        assert count == 2
        assert note is None
        assert extra == {}
        return f"{cfg.name}:{count}"

    result = cherries.main(experiment, profile=ProfileForTest(run))

    assert result == "Ada:2"
    assert recorder.params == [{"name": "Ada"}]
    assert recorder.ended == [None]
    assert {"cherries.entrypoint", "cherries.exp_dir", "cherries.start_time"} <= set(
        recorder.others
    )


def test_main_awaits_coroutine_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run, recorder = make_run(monkeypatch, tmp_path)

    async def experiment() -> str:
        return "finished"

    assert cherries.main(experiment, profile=ProfileForTest(run)) == "finished"
    assert recorder.ended == [None]


def test_main_ends_run_with_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run, recorder = make_run(monkeypatch, tmp_path)
    error = RuntimeError("failed")

    def experiment() -> None:
        raise error

    with pytest.raises(RuntimeError, match="failed"):
        cherries.main(experiment, profile=ProfileForTest(run))

    assert recorder.ended == [error]


def test_end_delegates_to_global_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock()
    monkeypatch.setattr(cherries.core, "run", run)

    cherries.end()

    run.end.assert_called_once_with()


def test_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", [__file__])
    monkeypatch.setattr(cherries.run, "exp_dir", tmp_path)

    class Config(cherries.BaseConfig):
        name: str = "world"
        source: Path = cherries.input(__file__, mkdir=True)
        temp: Path = cherries.temp("artifact.txt", mkdir=True)
        output: Path = cherries.output("hello.txt", mkdir=True)

    def main(cfg: Config) -> None:
        for x in range(10):
            y: float = x**2
            cherries.log_metrics({"x": x, "y": y})
        cfg.output.write_text(f"Hello, {cfg.name}!\n")
        cfg.temp.write_text("Temporary file.\n")
        logger.info("Hello, %s!", cfg.name)

    cherries.main(main, profile="debug")

import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import attrs
import pydantic
import pytest

from liblaf import cherries
from liblaf.cherries import core, profiles


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
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "experiment.py")])
    run = core.Run()
    entrypoint = tmp_path / "experiment.py"
    entrypoint.write_text("print('experiment')\n")
    monkeypatch.setattr(run, "entrypoint", entrypoint)
    monkeypatch.setattr(run, "project_dir", tmp_path)
    monkeypatch.setattr(run, "working_dir", tmp_path)
    recorder = RunRecorder()
    run.plugins.register(recorder)
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
    assert {"cherries/entrypoint", "cherries/exp_dir", "cherries/start_time"} <= set(
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
    monkeypatch.setattr(sys, "argv", ["experiment.py"])
    run, recorder = make_run(monkeypatch, tmp_path)
    source = tmp_path / "data" / "source.txt"
    source.parent.mkdir()
    source.write_text("source\n")

    class Config(cherries.BaseConfig):
        name: str = "world"
        source: Path = run.input("source.txt")
        temp: Path = run.temp("artifact.txt", mkdir=True)
        output: Path = run.output("hello.txt", mkdir=True)

    def main(cfg: Config) -> None:
        for x in range(10):
            y: float = x**2
            run.log_metrics({"x": x, "y": y})
        cfg.output.write_text(f"Hello, {cfg.name}!\n")
        cfg.temp.write_text("Temporary file.\n")

    cherries.main(main, profile=ProfileForTest(run))

    assert Config.model_fields["source"].default == source
    assert Config.model_fields["output"].default.read_text() == "Hello, world!\n"
    assert Config.model_fields["temp"].default.read_text() == "Temporary file.\n"
    assert recorder.ended == [None]
    assert run.get_metrics(iter(("x", "y"))).height == 20

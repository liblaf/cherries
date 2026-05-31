from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

import liblaf.cherries.plugins.comet as comet_module
from liblaf.cherries import core


def test_start_creates_comet_experiment_with_run_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExperimentConfig:
        def __init__(
            self,
            *,
            disabled: bool = False,
            name: str | None = None,
            tags: list[str] | None = None,
        ) -> None:
            self.disabled = disabled
            self.name = name
            self.tags = tags

    run = core.Run()
    run.project_name = "cherries"
    run.run_name = "exp/demo.py"
    run.tags = ["smoke", "local"]
    experiment = Mock()
    experiment.url = "https://www.comet.com/example"
    start = Mock(return_value=experiment)
    monkeypatch.setattr(comet_module.comet, "ExperimentConfig", ExperimentConfig)
    monkeypatch.setattr(comet_module.comet, "start", start)
    plugin = comet_module.Comet(run=run, disabled=True)

    plugin.start()

    assert start.call_args.kwargs["project_name"] == "cherries"
    config = start.call_args.kwargs["experiment_config"]
    assert config.disabled is True
    assert config.name == "exp/demo.py"
    assert config.tags == ["smoke", "local"]
    experiment.log_other.assert_called_once_with(
        "cherries/comet/url", "https://www.comet.com/example"
    )


def test_start_sets_name_and_tags_after_start_for_older_comet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExperimentConfig:
        def __init__(self, *, disabled: bool = False) -> None:
            self.disabled = disabled

    run = core.Run()
    run.project_name = "cherries"
    run.run_name = "exp/demo.py"
    run.tags = ["smoke"]
    experiment = Mock()
    experiment.url = "https://www.comet.com/example"
    start = Mock(return_value=experiment)
    monkeypatch.setattr(comet_module.comet, "ExperimentConfig", ExperimentConfig)
    monkeypatch.setattr(comet_module.comet, "start", start)
    plugin = comet_module.Comet(run=run, disabled=True)

    plugin.start()

    config = start.call_args.kwargs["experiment_config"]
    assert config.disabled is True
    experiment.set_name.assert_called_once_with("exp/demo.py")
    experiment.add_tags.assert_called_once_with(["smoke"])
    experiment.log_other.assert_called_once_with(
        "cherries/comet/url", "https://www.comet.com/example"
    )


def test_scalar_events_delegate_to_running_experiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = Mock()
    monkeypatch.setattr(
        comet_module.comet, "get_running_experiment", lambda: experiment
    )
    plugin = comet_module.Comet(run=core.Run())
    time = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    plugin.log_metric("loss", 0.25, step=2, time=time)
    plugin.log_metrics({"accuracy": 0.95}, step=3, time=time)
    plugin.log_other("phase", "train")
    plugin.log_others({"fold": 1})
    plugin.log_param("lr", 0.01)
    plugin.log_params({"epochs": 3})

    experiment.log_metric.assert_called_once_with("loss", 0.25, step=2)
    experiment.log_metrics.assert_called_once_with({"accuracy": 0.95}, step=3)
    experiment.log_other.assert_called_once_with("phase", "train")
    experiment.log_others.assert_called_once_with({"fold": 1})
    experiment.log_parameter.assert_called_once_with("lr", 0.01)
    experiment.log_parameters.assert_called_once_with({"epochs": 3})


def test_log_asset_is_currently_reserved_for_future_support(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    experiment = Mock()
    monkeypatch.setattr(
        comet_module.comet, "get_running_experiment", lambda: experiment
    )
    plugin = comet_module.Comet(run=core.Run())

    plugin.log_asset(tmp_path / "plot.png", metadata={"kind": "figure"})

    experiment.log_asset.assert_not_called()

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

import liblaf.cherries.plugins.logging as logging_module
from liblaf.cherries.plugins.logging import Logging


def test_logging_start_initializes_grapes_logging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init = Mock()
    monkeypatch.setattr(logging_module.grapes.logging, "init", init)
    entrypoint = tmp_path / "experiment.py"
    plugin = Logging()
    plugin.manager = SimpleNamespace(logs_dir=tmp_path / "logs", entrypoint=entrypoint)

    plugin.start()

    init.assert_called_once_with(
        file=tmp_path / "logs" / "experiment.log",
        force=True,
    )


def test_logging_mirrors_metrics_to_autolog(monkeypatch: pytest.MonkeyPatch) -> None:
    info = Mock()
    monkeypatch.setattr(logging_module.autolog, "info", info)
    plugin = Logging()

    plugin.log_metric("loss", 0.5)
    plugin.log_metric("loss", 0.25, step=2)
    plugin.log_metrics({"accuracy": 0.9})
    plugin.log_metrics({"accuracy": 0.95}, step=3)

    assert info.mock_calls == [
        call("%s: %s", "loss", 0.5),
        call("step: %s, %s: %s", 2, "loss", 0.25),
        call("%s", {"accuracy": 0.9}),
        call("step: %s, %s", 3, {"accuracy": 0.95}),
    ]

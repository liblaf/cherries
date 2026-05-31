import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import liblaf.logging
import pytest

from liblaf.cherries import core
from liblaf.cherries.plugins.logging import Logging


def test_logging_start_initializes_liblaf_logging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init = Mock()
    monkeypatch.setattr(liblaf.logging, "init", init)
    run = core.Run()
    entrypoint = tmp_path / "experiment.py"
    monkeypatch.setattr(run, "working_dir", tmp_path)
    monkeypatch.setattr(run, "entrypoint", entrypoint)
    plugin = Logging(run=run)

    plugin.start()

    init.assert_called_once_with(
        file=tmp_path / "logs" / "experiment.log",
        force=True,
    )


def test_logging_mirrors_metrics_to_python_logger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plugin = Logging(run=core.Run())
    time = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    with caplog.at_level(logging.INFO, logger="liblaf.cherries.plugins.logging"):
        plugin.log_metric("loss", 0.25, step=2, time=time)
        plugin.log_metrics({"accuracy": 0.95}, step=3, time=time)

    assert "step: 2, loss: 0.25" in caplog.text
    assert "step: 3, {'accuracy': 0.95}" in caplog.text

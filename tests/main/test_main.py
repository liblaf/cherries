import logging
import sys
from pathlib import Path

import pytest

from liblaf import cherries

logger: logging.Logger = logging.getLogger(__name__)


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

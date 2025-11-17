import logging
from pathlib import Path

import pytest

from liblaf import cherries

logger: logging.Logger = logging.getLogger(__name__)


def test_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.argv", [__file__])

    class Config(cherries.BaseConfig):
        name: str = "world"
        output: Path = cherries.output(tmp_path / "hello.txt")

    def main(cfg: Config) -> None:
        for x in range(10):
            y: float = x**2
            cherries.log_metrics({"x": x, "y": y})
        cfg.output.write_text(f"Hello, {cfg.name}!\n")
        logger.info("Hello, %s!", cfg.name)

    cherries.main(main, profile="playground")

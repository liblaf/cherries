import logging
from pathlib import Path

from liblaf import cherries

logger: logging.Logger = logging.getLogger(__name__)


def test_main(tmp_path: Path) -> None:
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

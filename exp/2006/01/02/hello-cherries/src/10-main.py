import logging
import time
from pathlib import Path

import liblaf.cherries as cherries  # noqa: PLR0402
from liblaf import grapes

logger = logging.getLogger(__name__)


class Config(cherries.BaseConfig):
    name: str = "world"
    output: Path = cherries.output("hello.txt")


def main(cfg: Config) -> None:
    for x in grapes.track(range(10), description="Progress"):
        y: float = x**2
        cherries.log_metrics({"x": x, "y": y})
        time.sleep(1)
    cfg.output.write_text(f"Hello, {cfg.name}!\n")
    logger.info("Hello, %s!", cfg.name)


if __name__ == "__main__":
    cherries.main(main)

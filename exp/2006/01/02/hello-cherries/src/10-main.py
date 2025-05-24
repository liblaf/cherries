import time
from pathlib import Path

from loguru import logger

import liblaf.cherries as cherries  # noqa: PLR0402
from liblaf import grapes


class Config(cherries.BaseConfig):
    input: Path = cherries.input("name.toml")
    output: Path = cherries.output("hello.txt")


def main(cfg: Config) -> None:
    name: str = grapes.load(cfg.input)["name"]
    for x in grapes.track(range(10), description="Progress"):
        y: float = x**2
        cherries.log_metrics({"x": x, "y": y})
        time.sleep(1)
    cfg.output.write_text(f"Hello, {name}!\n")
    logger.success("Hello, {}!", name)


if __name__ == "__main__":
    cherries.run(main, play=True)

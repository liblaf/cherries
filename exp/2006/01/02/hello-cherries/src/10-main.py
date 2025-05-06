from pathlib import Path

from loguru import logger

import liblaf.cherries as cherries  # noqa: PLR0402
from liblaf import grapes


class Config(cherries.BaseConfig):
    input: Path = cherries.inputs("name.toml")
    output: Path = cherries.outputs("hello.txt")


def main(cfg: Config) -> None:
    cherries.log_input(cfg.input)
    name: str = grapes.load(cfg.input)["name"]
    cfg.output.write_text(f"Hello, {name}!\n")
    logger.success("Hello, {}!", name)
    cherries.log_output(cfg.output)


if __name__ == "__main__":
    cherries.run(main)

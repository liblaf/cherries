from pathlib import Path

import loguru
import pydantic_settings as ps
from loguru import logger

import liblaf.cherries as cherries  # noqa: PLR0402
from liblaf import grapes

DEFAULT_FILTER: "loguru.FilterDict" = {
    "": "INFO",
    "__main__": "TRACE",
    "liblaf": "DEBUG",
}
DEFAULT_FILE_FILTER: "loguru.FilterDict" = {
    **DEFAULT_FILTER,
    "liblaf.cherries": "SUCCESS",
}


class PluginLogging(cherries.Plugin):
    model_config = ps.SettingsConfigDict(env_prefix=cherries.ENV_PREFIX + "LOGGING_")
    file: Path | None = Path("run.log")
    jsonl: Path | None = Path("run.log.jsonl")

    def _pre_start(self) -> None:
        handlers: list[loguru.HandlerConfig] = [grapes.logging.rich_handler()]
        if self.file is not None:
            handlers.append(grapes.logging.file_handler(self.file))
        if self.jsonl is not None:
            handlers.append(grapes.logging.jsonl_handler(self.jsonl))
        grapes.init_logging(handlers=handlers)

    def _pre_end(self, run: cherries.Experiment) -> None:
        logger.complete()
        if self.file is not None:
            run.upload_file("cherries/logging/run.log", self.file)
        if self.jsonl is not None:
            run.upload_file("cherries/logging/run.log.jsonl", self.jsonl)

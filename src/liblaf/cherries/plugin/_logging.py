import loguru
import pydantic_settings as ps
from loguru import logger

# TODO: fix PLR0402
# make pyright happy
import liblaf.grapes as grapes  # noqa: PLR0402
from liblaf import cherries

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

    def _pre_start(self) -> None:
        grapes.init_logging(
            handlers=[
                grapes.logging.console_handler(),
                grapes.logging.file_handler(),
                grapes.logging.jsonl_handler(),
            ]
        )

    def _pre_end(self, run: cherries.Experiment) -> None:
        logger.complete()
        run.upload_file("cherries/logging/run.log", "run.log")
        run.upload_file("cherries/logging/run.log.jsonl", "run.log.jsonl")

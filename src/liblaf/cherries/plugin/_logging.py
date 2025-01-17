import loguru
import pydantic_settings as ps
from loguru import logger
from rich.logging import RichHandler

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
                {
                    "sink": RichHandler(
                        console=grapes.logging.logging_console(),
                        omit_repeated_times=False,
                        markup=True,
                        log_time_format="[%Y-%m-%d %H:%M:%S]",
                    ),
                    "format": "{message}",
                    "filter": DEFAULT_FILTER,
                    "enqueue": True,
                },
                {
                    "sink": "run.log",
                    "filter": DEFAULT_FILE_FILTER,
                    "enqueue": True,
                    "mode": "w",
                },
                {
                    "sink": "run.log.jsonl",
                    "filter": DEFAULT_FILE_FILTER,
                    "serialize": True,
                    "enqueue": True,
                    "mode": "w",
                },
            ]
        )

    def _pre_end(self, run: cherries.Experiment) -> None:
        logger.complete()
        run.upload_file("cherries/logging/run.log", "run.log")
        run.upload_file("cherries/logging/run.log.jsonl", "run.log.jsonl")

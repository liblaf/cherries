import pydantic_settings as ps
from loguru import logger

# TODO: fix PLR0402
# make pyright happy
import liblaf.grapes as grapes  # noqa: PLR0402
from liblaf import cherries


class PluginLogging(cherries.Plugin):
    model_config = ps.SettingsConfigDict(env_prefix=cherries.ENV_PREFIX + "LOGGING_")

    def _pre_start(self) -> None:
        grapes.init_logging()
        logger.add("run.log", enqueue=True, mode="w")
        logger.add("run.log.jsonl", serialize=True, enqueue=True, mode="w")

    def _pre_end(self, run: cherries.Experiment) -> None:
        logger.complete()
        run.upload_file("cherries/logging/run.log", "run.log")
        run.upload_file("cherries/logging/run.log.jsonl", "run.log.jsonl")

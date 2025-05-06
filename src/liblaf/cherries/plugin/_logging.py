from typing import override

import attrs
from loguru import logger

from liblaf import grapes

from ._abc import End, Start
from ._run import run


@attrs.define(eq=True, order=True)
class LoggingEnd(End):
    @override
    def __call__(self) -> None:
        logger.complete()
        run.log_artifact("run.log")
        run.log_artifact("run.log.jsonl")


@attrs.define(eq=True, order=True)
class LoggingStart(Start):
    @override
    def __call__(self) -> None:
        grapes.init_logging()

from typing import override

import attrs
from loguru import logger

from liblaf import grapes

from ._abc import End, RunStatus, Start
from ._run import run


@attrs.define
class LoggingEnd(End):
    @override
    def __call__(self, status: RunStatus = RunStatus.FINISHED) -> None:
        logger.complete()
        run.log_artifact(run.exp_dir / "run.log")
        run.log_artifact(run.exp_dir / "run.log.jsonl")


@attrs.define
class LoggingStart(Start):
    @override
    def __call__(self) -> None:
        grapes.init_logging(
            handlers=[
                grapes.logging.rich_handler(),
                grapes.logging.file_handler(file=run.exp_dir / "run.log"),
                grapes.logging.jsonl_handler(run.exp_dir / "run.log.jsonl"),
            ]
        )

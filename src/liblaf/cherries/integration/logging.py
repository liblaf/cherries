from typing import override

import attrs
import loguru
from loguru import logger

from liblaf import grapes

from . import _abc
from ._exp import exp


@attrs.define
class End(_abc.End):
    priority: int = attrs.field(default=-1, kw_only=True)  # before Comet
    text: bool = True
    jsonl: bool = False

    @override
    def __call__(self, **kwargs) -> None:
        logger.complete()
        if self.text and (exp.exp_dir / "run.log").exists():
            exp.log_asset(exp.exp_dir / "run.log")
        if self.jsonl and (exp.exp_dir / "run.log.jsonl").exists():
            exp.log_asset(exp.exp_dir / "run.log.jsonl")


@attrs.define
class Start(_abc.Start):
    priority: int = attrs.field(default=-1, kw_only=True)  # before Comet
    text: bool = True
    jsonl: bool = False

    @override
    def __call__(self, **kwargs) -> None:
        handlers: list[loguru.HandlerConfig] = [
            grapes.logging.rich_handler(enable_link=False)
        ]
        if self.text:
            handlers.append(grapes.logging.file_handler(sink=exp.exp_dir / "run.log"))
        if self.jsonl:
            handlers.append(
                grapes.logging.jsonl_handler(sink=exp.exp_dir / "run.log.jsonl")
            )
        grapes.init_logging(handlers=handlers)

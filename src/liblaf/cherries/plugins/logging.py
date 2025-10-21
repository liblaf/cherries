from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
from loguru import logger

from liblaf import grapes
from liblaf.cherries import core


@attrs.define
class Logging(core.Run):
    @property
    def log_file(self) -> Path:
        return self.exp_dir / "logs" / self.entrypoint.with_suffix(".log").name

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        grapes.logging.init(enable_link=False, file=self.log_file)

    @override
    @core.impl
    def log_metric(
        self,
        name: str,
        value: Any,
        /,
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None:
        __tracebackhide__ = True
        if step is None:
            logger.info("{name}: {value}", name=name, value=value)
        else:
            logger.info(
                "step: {step}, {name}: {value}", step=step, name=name, value=value
            )

    @override
    @core.impl
    def log_metrics(
        self,
        dic: Mapping[str, Any],
        /,
        prefix: str | None = None,
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None:
        __tracebackhide__ = True
        if step is None:
            logger.info("{dic}", dic=dic)
        else:
            logger.info("step: {step}, {dic}", step=step, dic=dic)

    @override
    @core.impl
    def end(self, *args, **kwargs) -> None:
        self.plugin_root.log_asset(self.log_file, "run.log")

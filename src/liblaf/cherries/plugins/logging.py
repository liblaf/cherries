import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
from liblaf.grapes.logging import autolog

from liblaf import grapes
from liblaf.cherries import core


@attrs.define
class Logging(core.PluginSchema):
    @property
    def log_file(self) -> Path:
        return self.run.logs_dir / self.run.entrypoint.with_suffix(".log").name

    @override
    @core.impl(before=("Comet",))
    def end(self, *args, **kwargs) -> None:
        self.run.log_asset(self.log_file)

    @override
    @core.impl
    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None:
        __tracebackhide__ = True
        if step is None:
            autolog.info("%s: %s", name, value)
        else:
            autolog.info("step: %s, %s: %s", step, name, value)

    @override
    @core.impl
    def log_metrics(
        self, metrics: Mapping[str, Any], step: int | None = None, **kwargs
    ) -> None:
        __tracebackhide__ = True
        if step is None:
            autolog.info("%s", metrics)
        else:
            autolog.info("step: %s, %s", step, metrics)

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        grapes.logging.init(file=self.log_file, force=True)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.CRITICAL)

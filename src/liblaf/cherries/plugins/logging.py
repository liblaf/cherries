import functools
import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import override

import attrs
import liblaf.logging

from liblaf.cherries import core

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Logging(core.Plugin, core.PluginProtocol):
    """Initialize Python logging and mirror metrics to the run log.

    Attributes:
        run: Run that owns this plugin.
    """

    run: core.Run

    @functools.cached_property
    def log_file(self) -> Path:
        """Default log file below the run working directory."""
        return (
            self.run.working_dir / "logs" / self.run.entrypoint.with_suffix(".log").name
        )

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        """Initialize `liblaf.logging` for the run log file."""
        liblaf.logging.init(file=self.log_file, force=True)

    @override
    @core.impl
    def log_metric(self, name: str, value: float, *, step: int, time: datetime) -> None:
        """Write one metric to the Python logger."""
        logger.info("step: %s, %s: %s", step, name, value)

    @override
    @core.impl
    def log_metrics(
        self, metrics: Mapping[str, float], *, step: int, time: datetime
    ) -> None:
        """Write multiple metrics to the Python logger."""
        logger.info("step: %s, %s", step, metrics)

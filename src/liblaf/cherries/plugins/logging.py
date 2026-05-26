import functools
from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
from liblaf.grapes.logging import autolog

from liblaf import grapes
from liblaf.cherries import core


@attrs.define
class Logging(core.Plugin, core.PluginProtocol):
    """Initialize Python logging and mirror metrics to the logger.

    The plugin creates a log file beside the experiment and mirrors metric
    calls through `liblaf.grapes.logging.autolog`, making local runs readable
    even when no remote tracker is enabled.
    """

    @functools.cached_property
    def log_file(self) -> Path:
        """Default log file path for the current run."""
        return self.manager.logs_dir / self.manager.entrypoint.with_suffix(".log").name

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        """Initialize logging with the run log file."""
        grapes.logging.init(file=self.log_file, force=True)

    @override
    @core.impl
    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None:
        """Log one metric at the optional step."""
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
        """Log a mapping of metrics at the optional step."""
        __tracebackhide__ = True
        if step is None:
            autolog.info("%s", metrics)
        else:
            autolog.info("step: %s, %s", step, metrics)

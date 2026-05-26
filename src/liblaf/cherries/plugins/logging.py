import functools
from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
import liblaf.logging as _log

from liblaf.cherries import core


@attrs.define
class Logging(core.Plugin, core.PluginProtocol):
    """Initialize Python logging and mirror metrics to the logger.

    The plugin creates a log file beside the experiment and mirrors metric
    calls through `liblaf.logging`, making local runs readable even when no
    remote tracker is enabled.
    """

    @functools.cached_property
    def log_file(self) -> Path:
        """Default log file path for the current run."""
        return self.manager.logs_dir / self.manager.entrypoint.with_suffix(".log").name

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        """Initialize logging with the run log file."""
        _log.init(file=self.log_file, force=True)

    @override
    @core.impl
    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None:
        """Log one metric at the optional step."""
        __tracebackhide__ = True
        if step is None:
            _log.info("%s: %s", name, value)
        else:
            _log.info("step: %s, %s: %s", step, name, value)

    @override
    @core.impl
    def log_metrics(
        self, metrics: Mapping[str, Any], step: int | None = None, **kwargs
    ) -> None:
        """Log a mapping of metrics at the optional step."""
        __tracebackhide__ = True
        if step is None:
            _log.info("%s", metrics)
        else:
            _log.info("step: %s, %s", step, metrics)

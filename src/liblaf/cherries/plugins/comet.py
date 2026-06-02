import logging
import unittest.mock
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, override

import attrs
import comet_ml as comet

from liblaf.cherries import core

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Comet(core.Plugin, core.PluginProtocol):
    """Send run metadata, parameters, and metrics to Comet.

    Attributes:
        run: Run that owns this plugin.
        disabled: Whether to start Comet in disabled/offline mode.
    """

    run: core.Run = attrs.field(repr=False)
    disabled: bool = attrs.field(default=False)

    @property
    def experiment(self) -> comet.CometExperiment:
        """Currently running Comet experiment, or a mock fallback."""
        return comet.get_running_experiment() or unittest.mock.MagicMock()

    @override
    @core.impl
    def start(self) -> None:
        """Start a Comet experiment for the owning run."""
        try:
            exp: comet.CometExperiment = comet.start(
                project_name=self.run.project_name,
                experiment_config=comet.ExperimentConfig(
                    disabled=self.disabled, name=self.run.run_name, tags=self.run.tags
                ),
            )
        except ValueError:
            logger.exception("")
        else:
            self.run.log_other("cherries/comet/url", exp.url)

    @override
    @core.impl(after=("Git",))
    def end(self, exc: BaseException | None = None) -> None:
        """End the active Comet experiment after Git finalization."""
        self.experiment.end()

    @override
    @core.impl
    def log_asset(
        self,
        path: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        report: bool = True,
    ) -> None:
        """Reserve the asset hook for future Comet artifact support."""
        # TODO: `log_remote_asset` once CAS infra is ready

    @override
    @core.impl
    def log_metric(self, name: str, value: float, *, step: int, time: datetime) -> None:
        """Log one metric to Comet."""
        return self.experiment.log_metric(name, value, step=step)

    @override
    @core.impl
    def log_metrics(
        self, metrics: dict[str, float], *, step: int, time: datetime
    ) -> None:
        """Log multiple metrics to Comet."""
        return self.experiment.log_metrics(metrics, step=step)

    @override
    @core.impl
    def log_other(self, name: str, value: Any) -> None:
        """Log one metadata value to Comet."""
        return self.experiment.log_other(name, value)

    @override
    @core.impl
    def log_others(self, others: dict[str, Any]) -> None:
        """Log multiple metadata values to Comet."""
        return self.experiment.log_others(others)

    @override
    @core.impl
    def log_param(self, name: str, value: Any) -> None:
        """Log one parameter to Comet."""
        return self.experiment.log_parameter(name, value)

    @override
    @core.impl
    def log_params(self, params: dict[str, Any]) -> None:
        """Log multiple parameters to Comet."""
        return self.experiment.log_parameters(params)

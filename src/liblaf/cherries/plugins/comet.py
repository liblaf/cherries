from __future__ import annotations

import inspect
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

    run: core.Run
    disabled: bool = attrs.field(default=False)

    @property
    def experiment(self) -> comet.CometExperiment:
        """Currently running Comet experiment, or a mock fallback."""
        return comet.get_running_experiment() or unittest.mock.MagicMock()

    @override
    @core.impl
    def start(self) -> None:
        """Start a Comet experiment for the owning run."""
        config_kwargs: dict[str, Any] = {"disabled": self.disabled}
        config_params = inspect.signature(comet.ExperimentConfig).parameters
        supports_name = "name" in config_params
        supports_tags = "tags" in config_params
        if supports_name:
            config_kwargs["name"] = self.run.run_name
        if supports_tags:
            config_kwargs["tags"] = self.run.tags
        try:
            exp: comet.CometExperiment = comet.start(
                project_name=self.run.project_name,
                experiment_config=comet.ExperimentConfig(**config_kwargs),
            )
        except ValueError:
            logger.exception("")
        else:
            if not supports_name and hasattr(exp, "set_name"):
                exp.set_name(self.run.run_name)
            if not supports_tags and self.run.tags and hasattr(exp, "add_tags"):
                exp.add_tags(self.run.tags)
            exp.log_other("cherries/comet/url", exp.url)

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
        # TODO: use `log_remote_asset`

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
        return self.experiment.log_metrics(dict(metrics), step=step)

    @override
    @core.impl
    def log_other(self, name: str, value: Any) -> None:
        """Log one metadata value to Comet."""
        return self.experiment.log_other(name, value)

    @override
    @core.impl
    def log_others(self, others: Mapping[str, Any]) -> None:
        """Log multiple metadata values to Comet."""
        return self.experiment.log_others(dict(others))

    @override
    @core.impl
    def log_param(self, name: str, value: Any) -> None:
        """Log one parameter to Comet."""
        return self.experiment.log_parameter(name, value)

    @override
    @core.impl
    def log_params(self, params: Mapping[str, Any]) -> None:
        """Log multiple parameters to Comet."""
        return self.experiment.log_parameters(dict(params))

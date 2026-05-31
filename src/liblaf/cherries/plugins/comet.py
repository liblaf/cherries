from __future__ import annotations

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
    run: core.Run
    disabled: bool = attrs.field(default=False)

    @property
    def experiment(self) -> comet.CometExperiment:
        return comet.get_running_experiment() or unittest.mock.MagicMock()

    @override
    @core.impl
    def start(self) -> None:
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
            exp.log_other("cherries/comet/url", exp.url)

    @override
    @core.impl(after=("Git",))
    def end(self, exc: BaseException | None = None) -> None:
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
        # TODO: use `log_remote_asset`
        pass

    @override
    @core.impl
    def log_metric(self, name: str, value: float, *, step: int, time: datetime) -> None:
        return self.experiment.log_metric(name, value, step=step)

    @override
    @core.impl
    def log_metrics(
        self, metrics: dict[str, float], *, step: int, time: datetime
    ) -> None:
        return self.experiment.log_metrics(dict(metrics), step=step)

    @override
    @core.impl
    def log_other(self, name: str, value: Any) -> None:
        return self.experiment.log_other(name, value)

    @override
    @core.impl
    def log_others(self, others: Mapping[str, Any]) -> None:
        return self.experiment.log_others(dict(others))

    @override
    @core.impl
    def log_param(self, name: str, value: Any) -> None:
        return self.experiment.log_parameter(name, value)

    @override
    @core.impl
    def log_params(self, params: Mapping[str, Any]) -> None:
        return self.experiment.log_parameters(dict(params))

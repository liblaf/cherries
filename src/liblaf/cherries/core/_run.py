from collections.abc import Mapping
from pathlib import Path
from typing import Any

import attrs

from liblaf.cherries import paths

from ._plugin import Plugin
from ._spec import spec


@attrs.define
class Run(Plugin):
    """.

    References:
        1. [Experiment - Comet Docs](https://www.comet.com/docs/v2/api-and-sdk/python-sdk/reference/Experiment/)
        2. [Logger | ClearML](https://clear.ml/docs/latest/docs/references/sdk/logger)
        3. [MLflow Tracking APIs | MLflow](https://www.mlflow.org/docs/latest/ml/tracking/tracking-api/)
    """

    @property
    def exp_dir(self) -> Path:
        return paths.exp_dir(absolute=True)

    @property
    def url(self) -> str:
        return self.get_url()

    @spec
    def end(self, *args, **kwargs) -> None: ...
    @spec(first_result=True)
    def get_url(self) -> str: ...
    @spec
    def log_asset(self, *args, **kwargs) -> None: ...
    @spec
    def log_asset_data(self, *args, **kwargs) -> None: ...
    @spec
    def log_asset_folder(self, *args, **kwargs) -> None: ...
    @spec
    def log_input(self, *args, **kwargs) -> None: ...
    @spec
    def log_input_folder(self, *args, **kwargs) -> None: ...
    @spec
    def log_metric(
        self,
        name: str,
        value: Any,
        /,
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None: ...
    @spec
    def log_metrics(
        self,
        dic: Mapping[str, Any],
        /,
        prefix: str | None = None,
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None: ...
    @spec
    def log_other(self, key: Any, value: Any, /, **kwargs) -> None: ...
    @spec
    def log_others(self, dictionary: Mapping[Any, Any], /, **kwargs) -> None: ...
    @spec
    def log_output(self, *args, **kwargs) -> None: ...
    @spec
    def log_output_folder(self, *args, **kwargs) -> None: ...
    @spec
    def log_parameter(
        self, name: Any, value: Any, /, step: int | None = None, **kwargs
    ) -> None: ...
    @spec
    def log_parameters(
        self,
        parameters: Mapping[Any, Any],
        /,
        prefix: str | None = None,
        step: int | None = None,
        **kwargs,
    ) -> None: ...

    @spec(delegate=False)
    def start(self, *args, **kwargs) -> None:
        self._prepare()
        self.delegate("start", args, kwargs)


active_run: Run = Run()
end = active_run.end
log_asset = active_run.log_asset
log_asset_data = active_run.log_asset_data
log_asset_folder = active_run.log_asset_folder
log_input = active_run.log_input
log_input_folder = active_run.log_input_folder
log_metric = active_run.log_metric
log_metrics = active_run.log_metrics
log_other = active_run.log_other
log_others = active_run.log_others
log_output = active_run.log_output
log_output_folder = active_run.log_output_folder
log_parameter = active_run.log_parameter
log_parameters = active_run.log_parameters
start = active_run.start

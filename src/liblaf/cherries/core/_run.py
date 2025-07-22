from pathlib import Path

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
    def get_url(self, *args, **kwargs) -> str: ...
    @spec
    def log_asset(self, *args, **kwargs) -> None: ...
    @spec
    def log_asset_data(self, *args, **kwargs) -> None: ...
    @spec
    def log_asset_folder(self, *args, **kwargs) -> None: ...
    @spec
    def log_metric(self, *args, **kwargs) -> None: ...
    @spec
    def log_metrics(self, *args, **kwargs) -> None: ...
    @spec
    def log_other(self, *args, **kwargs) -> None: ...
    @spec
    def log_others(self, *args, **kwargs) -> None: ...
    @spec
    def log_parameter(self, *args, **kwargs) -> None: ...
    @spec
    def log_parameters(self, *args, **kwargs) -> None: ...

    @spec(delegate=False)
    def start(self, *args, **kwargs) -> None:
        self._prepare()
        self.delegate("start", args, kwargs)


active_run: Run = Run()
log_asset = active_run.log_asset
log_metrics = active_run.log_metrics

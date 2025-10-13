import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import attrs

from liblaf.cherries import path_utils
from liblaf.cherries.typing import PathLike

from ._plugin import Plugin
from ._spec import spec
from ._utils import plugin_cached_property, plugin_property


@attrs.define
class Run(Plugin):
    """.

    References:
        1. [Experiment - Comet Docs](https://www.comet.com/docs/v2/api-and-sdk/python-sdk/reference/Experiment/)
        2. [Logger | ClearML](https://clear.ml/docs/latest/docs/references/sdk/logger)
        3. [MLflow Tracking APIs | MLflow](https://www.mlflow.org/docs/latest/ml/tracking/tracking-api/)
    """

    @plugin_cached_property
    def data_dir(self) -> Path:
        return path_utils.data()

    @plugin_cached_property
    def entrypoint(self) -> Path:
        return path_utils.entrypoint()

    @plugin_cached_property
    def exp_dir(self) -> Path:
        return path_utils.exp_dir()

    @plugin_cached_property
    def exp_name(self) -> str:
        return (
            self.entrypoint.relative_to(self.project_dir)
            .as_posix()
            .removeprefix("exp/")
        )

    @plugin_property
    def params(self) -> Mapping[str, Any]:
        return self.plugin_root.get_params()

    @plugin_cached_property
    def project_name(self) -> str | None:
        return self.project_dir.name

    @plugin_cached_property
    def project_dir(self) -> Path:
        return path_utils.project_dir()

    @plugin_cached_property
    def start_time(self) -> datetime.datetime:
        return datetime.datetime.now().astimezone()

    @plugin_property
    def url(self) -> str:
        return self.plugin_root.get_url()

    @spec
    def end(self, *args, **kwargs) -> None: ...

    @spec(first_result=True)
    def get_others(self) -> Mapping[str, Any]: ...

    @spec(first_result=True)
    def get_params(self) -> Mapping[str, Any]: ...

    @spec(first_result=True)
    def get_url(self) -> str: ...

    @spec
    def log_asset(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None: ...

    @spec
    def log_input(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None: ...

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
    def log_output(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None: ...

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

    @spec
    def start(self, *args, **kwargs) -> None: ...


active_run: Run = Run()
end = active_run.end
log_asset = active_run.log_asset
log_input = active_run.log_input
log_metric = active_run.log_metric
log_metrics = active_run.log_metrics
log_other = active_run.log_other
log_others = active_run.log_others
log_output = active_run.log_output
log_parameter = active_run.log_parameter
log_parameters = active_run.log_parameters
start = active_run.start

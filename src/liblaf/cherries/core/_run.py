import contextlib
import datetime
import functools
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import attrs
import git

from liblaf.cherries import paths
from liblaf.cherries.typed import PathLike

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

    @functools.cached_property
    def data_dir(self) -> Path:
        if self._plugin_parent is not None:
            return self.plugin_root.data_dir
        return paths.data()

    @functools.cached_property
    def entrypoint(self) -> Path:
        if self._plugin_parent is not None:
            return self.plugin_root.entrypoint
        return paths.entrypoint()

    @functools.cached_property
    def exp_dir(self) -> Path:
        if self._plugin_parent is not None:
            return self.plugin_root.exp_dir
        return paths.exp_dir()

    @functools.cached_property
    def name(self) -> str:
        if self._plugin_parent is not None:
            return self.plugin_root.name
        return self.start_time.strftime("%Y-%m-%dT%H%M%S")

    @property
    def params(self) -> Mapping[str, Any]:
        if self._plugin_parent is not None:
            return self.plugin_root.params
        return self.get_params()

    @functools.cached_property
    def project_name(self) -> str | None:
        if self._plugin_parent is not None:
            return self.plugin_root.project_name
        try:
            repo: git.Repo = git.Repo(search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            return None
        else:
            return Path(repo.working_dir).name

    @functools.cached_property
    def root_dir(self) -> Path:
        if self._plugin_parent is not None:
            return self.plugin_root.root_dir
        try:
            repo: git.Repo = git.Repo(search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            return self.entrypoint.parent
        else:
            return Path(repo.working_dir).absolute()

    @functools.cached_property
    def start_time(self) -> datetime.datetime:
        if self._plugin_parent is not None:
            return self.plugin_root.start_time
        return datetime.datetime.now().astimezone()

    @functools.cached_property
    def url(self) -> str:
        if self._plugin_parent is not None:
            return self.plugin_root.url
        return self.get_url()

    @spec
    def end(self, *args, **kwargs) -> None: ...

    @spec(first_result=True)
    def get_others(self) -> Mapping[str, Any]: ...

    @spec(first_result=True)
    def get_params(self) -> Mapping[str, Any]: ...

    @spec(first_result=True)
    def get_url(self) -> str: ...

    @spec(delegate=False)
    def log_asset(
        self,
        path: PathLike,
        name: PathLike | None = None,
        *,
        metadata: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> None:
        if name is None:
            path = Path(path)
            with contextlib.suppress(ValueError):
                name = path.relative_to(self.data_dir)
        self.delegate("log_asset", (path, name), {"metadata": metadata, **kwargs})

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

    @spec(delegate=False)
    def start(self, *args, **kwargs) -> None:
        self._plugins_prepare()
        self.delegate("start", args, kwargs)


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

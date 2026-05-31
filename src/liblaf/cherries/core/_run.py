from __future__ import annotations

import functools
import logging
import os
import shlex
import sys
import traceback
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, SupportsFloat, cast

import attrs
import git
import git.exc
import polars as pl
from environs import env

from liblaf.cherries import utils

from .assets import AssetPluginProtocol, AssetsManager
from .assets.bundle import relative_or_absolute
from .metrics import MetricPluginProtocol, MetricsLike, MetricsManager
from .others import OtherPluginProtocol, OthersManager
from .params import ParamPluginProtocol, ParamsManager
from .plugin import PluginManager

if TYPE_CHECKING:
    from _typeshed import StrPath

logger: logging.Logger = logging.getLogger(__name__)

_PATH_SKIP_NAMES: set[str] = {"exp", "src"}


@attrs.define
class Run:
    def _default_assets(self) -> AssetsManager:
        return AssetsManager(
            working_dir=self.working_dir,
            plugins=cast("AssetPluginProtocol", self.plugins),
        )

    def _default_metrics(self) -> MetricsManager:
        return MetricsManager(plugins=cast("MetricPluginProtocol", self.plugins))

    def _default_others(self) -> OthersManager:
        return OthersManager(plugins=cast("OtherPluginProtocol", self.plugins))

    def _default_params(self) -> ParamsManager:
        return ParamsManager(plugins=cast("ParamPluginProtocol", self.plugins))

    plugins: PluginManager = attrs.field(factory=PluginManager)
    _assets: AssetsManager = attrs.field(
        default=attrs.Factory(_default_assets, takes_self=True), kw_only=True
    )
    _metrics: MetricsManager = attrs.field(
        default=attrs.Factory(_default_metrics, takes_self=True), kw_only=True
    )
    _others: OthersManager = attrs.field(
        default=attrs.Factory(_default_others, takes_self=True), kw_only=True
    )
    _params: ParamsManager = attrs.field(
        default=attrs.Factory(_default_params, takes_self=True), kw_only=True
    )

    @functools.cached_property
    def entrypoint(self) -> Path:
        if sys.argv[0] == "-c":
            return Path(os.devnull).resolve()
        return Path(sys.argv[0]).resolve()

    @functools.cached_property
    def project_dir(self) -> Path:
        if self.repo is None:
            return Path.cwd().resolve()
        return Path(self.repo.working_dir).resolve()

    @functools.cached_property
    def project_name(self) -> str:
        if self.repo is not None:
            try:
                remote: git.Remote = self.repo.remote()
                parsed: utils.GitUrlParsed = utils.giturlparse(remote.url)
            except ValueError:
                pass
            else:
                return parsed.repo
        return self.project_dir.name

    @functools.cached_property
    def repo(self) -> git.Repo | None:
        try:
            return git.Repo(search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as err:
            logger.warning("%s", err)
            return None

    @functools.cached_property
    def run_name(self) -> str:
        if name := env.str("CHERRIES_NAME", ""):
            return name
        name: str = self.entrypoint.relative_to(self.project_dir).as_posix()
        while True:
            original: str = name
            for folder in _PATH_SKIP_NAMES:
                name: str = name.removeprefix(f"{folder}/")
            if name == original:
                break
        return name

    @functools.cached_property
    def start_time(self) -> datetime:
        return datetime.now().astimezone()

    @functools.cached_property
    def tags(self) -> list[str]:
        return env.list("CHERRIES_TAGS", [])

    @functools.cached_property
    def working_dir(self) -> Path:
        parent: Path = self.entrypoint.parent
        while parent.name in _PATH_SKIP_NAMES:
            parent: Path = parent.parent
        return parent

    # region Lifecycle

    def start(self) -> None:
        """Start plugins and record Cherries run metadata."""
        self.plugins.delegate("start")
        entrypoint: Path = relative_or_absolute(self.entrypoint, self.project_dir)
        exp_dir: Path = relative_or_absolute(self.working_dir, self.project_dir)
        self.log_other("cherries/cmd", shlex.join(sys.orig_argv))
        self.log_other("cherries/entrypoint", entrypoint)
        self.log_other("cherries/exp_dir", exp_dir)
        self.log_other("cherries/start_time", self.start_time)

    def end(self, exc: BaseException | None = None) -> None:
        self.log_other("cherries/end_time", datetime.now().astimezone())
        if exc is not None:
            self.log_other(
                "cherries/exception", "\n".join(traceback.format_exception_only(exc))
            )
        self._assets.end()
        self.plugins.delegate("end", exc=exc)

    # endregion Lifecycle

    # region Metrics

    @property
    def step(self) -> int:
        return self._metrics.step

    @step.setter
    def step(self, value: int) -> None:
        self._metrics.step = value

    def get_step(self) -> int:
        return self.step

    def set_step(self, step: int) -> None:
        self.step = step

    def get_metric(self, name: str) -> pl.DataFrame:
        return self._metrics.get_metric(name)

    def log_metric(
        self,
        name: str,
        value: SupportsFloat,
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        self._metrics.log_metric(name, value, step=step, time=time)

    def get_metrics(self, metrics: Iterator[str] | None = None) -> pl.DataFrame:
        return self._metrics.get_metrics(metrics)

    def log_metrics(
        self,
        metrics: MetricsLike,
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        self._metrics.log_metrics(metrics, step=step, time=time)

    # endregion Metrics

    # region Assets

    def input(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> Path:
        return self._assets.input(path, metadata=metadata)

    def output(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        return self._assets.output(path, metadata=metadata, mkdir=mkdir)

    def temp(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        return self._assets.temp(path, metadata=metadata, mkdir=mkdir)

    def log_asset(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        self._assets.log_asset(path, metadata=metadata)

    def log_input(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        self._assets.log_input(path, metadata=metadata)

    def log_output(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        self._assets.log_output(path, metadata=metadata)

    def log_temp(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        self._assets.log_temp(path, metadata=metadata)

    # endregion Assets

    # region Logging

    def get_other(self, name: str) -> Any:
        return self._others.get_other(name)

    def log_other(self, name: str, value: Any) -> None:
        self._others.log_other(name, value)

    def get_others(self) -> dict[str, Any]:
        return self._others.get_others()

    def log_others(self, others: Mapping[str, Any]) -> None:
        self._others.log_others(others)

    def get_param(self, name: str) -> Any:
        return self._params.get_param(name)

    def log_param(self, name: str, value: Any) -> None:
        self._params.log_param(name, value)

    def get_params(self) -> dict[str, Any]:
        return self._params.get_params()

    def log_params(self, params: Mapping[str, Any]) -> None:
        self._params.log_params(params)

    # endregion Logging

    def summary(self, prefix: StrPath | None = None) -> dict[str, Any]:
        summary: dict[str, Any] = {"name": self.run_name}
        others: dict[str, Any] = self.get_others()
        summary.update(others.pop("cherries"))
        summary["params"] = self.get_params()
        summary.update(self._assets.summary.to_dict(prefix=prefix))
        summary["others"] = others
        return summary

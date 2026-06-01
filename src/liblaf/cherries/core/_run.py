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
from slugify import slugify

from liblaf.cherries.utils import GitUrlParsed, giturlparse, relative_or_absolute

from .assets import AssetPluginProtocol, AssetsManager
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
    """Mutable state for one Cherries experiment run.

    A `Run` owns plugin registration, path helpers, metrics, parameters, and
    miscellaneous metadata. Profiles configure the process-global run, while
    [`main`][liblaf.cherries.main] starts and ends it around an experiment
    callable.
    """

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
        """Python entrypoint used to derive the experiment name and folders."""
        if sys.argv[0] == "-c":
            return Path(os.devnull).resolve()
        return Path(sys.argv[0]).resolve()

    @functools.cached_property
    def project_dir(self) -> Path:
        """Git repository root, or the current directory outside a Git repo."""
        if self.repo is None:
            return Path.cwd().resolve()
        return Path(self.repo.working_dir).resolve()

    @functools.cached_property
    def project_name(self) -> str:
        """Project name reported to plugins."""
        if self.repo is None:
            return self.project_dir.name
        try:
            remote: git.Remote = self.repo.remote()
            parsed: GitUrlParsed = giturlparse(remote.url)
        except ValueError:
            return self.project_dir.name
        else:
            return parsed.repo

    @functools.cached_property
    def repo(self) -> git.Repo | None:
        try:
            return git.Repo(search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as exc:
            logger.warning("%s", exc)

    @functools.cached_property
    def run_key(self) -> Path:
        run_key: Path = self.entrypoint.relative_to(self.project_dir)
        run_key: Path = _strip_path(run_key)
        run_key: Path = run_key.with_suffix("")
        run_key /= f"{self.start_time.strftime('%Y-%m-%dT%H%M%S')}-{self.run_slug}"
        return run_key

    @functools.cached_property
    def run_name(self) -> str:
        """Run name from `CHERRIES_NAME` or the entrypoint path."""
        if name := env.str("CHERRIES_NAME", ""):
            return name
        run_path: Path = self.entrypoint.relative_to(self.project_dir)
        run_path: Path = _strip_path(run_path)
        run_path: Path = run_path.with_suffix("")
        return run_path.as_posix()

    @functools.cached_property
    def run_slug(self) -> str:
        return slugify(self.run_name, lowercase=False, allow_unicode=True)

    @functools.cached_property
    def start_time(self) -> datetime:
        """Timezone-aware timestamp captured when the run object is first used."""
        return datetime.now().astimezone()

    @functools.cached_property
    def tags(self) -> list[str]:
        """Tags parsed from the `CHERRIES_TAGS` environment variable."""
        return env.list("CHERRIES_TAGS", [])

    @functools.cached_property
    def working_dir(self) -> Path:
        """Directory used to resolve data, temporary, log, and local snapshot paths."""
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
        """Flush artifacts, record shutdown metadata, and end plugins.

        Args:
            exc: Exception raised by the experiment, if any.
        """
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
        """Default metric step."""
        return self._metrics.step

    @step.setter
    def step(self, value: int) -> None:
        self._metrics.step = value

    def get_step(self) -> int:
        """Return the default metric step."""
        return self.step

    def set_step(self, step: int) -> None:
        """Set the default metric step."""
        self.step = step

    def get_metric(self, name: str) -> pl.DataFrame:
        """Return one metric series."""
        return self._metrics.get_metric(name)

    def log_metric(
        self,
        name: str,
        value: SupportsFloat,
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        """Log one scalar metric."""
        self._metrics.log_metric(name, value, step=step, time=time)

    def get_metrics(self, metrics: Iterator[str] | None = None) -> pl.DataFrame:
        """Return selected metric series concatenated into one dataframe."""
        return self._metrics.get_metrics(metrics)

    def log_metrics(
        self,
        metrics: MetricsLike,
        *,
        step: int | None = None,
        time: datetime | None = None,
    ) -> None:
        """Log multiple scalar metrics, flattening nested mappings with `/`."""
        self._metrics.log_metrics(metrics, step=step, time=time)

    # endregion Metrics

    # region Assets

    def input(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> Path:
        """Resolve and immediately log an input below `data/`."""
        return self._assets.input(path, metadata=metadata)

    def output(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        """Resolve an output below `data/` and queue it until run end."""
        return self._assets.output(path, metadata=metadata, mkdir=mkdir)

    def temp(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        """Resolve a temporary artifact below `tmp/` and queue it until run end."""
        return self._assets.temp(path, metadata=metadata, mkdir=mkdir)

    def log_asset(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        """Log an existing generic artifact immediately."""
        self._assets.log_asset(path, metadata=metadata)

    def log_input(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        """Log an existing input artifact immediately."""
        self._assets.log_input(path, metadata=metadata)

    def log_output(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        """Log an existing output artifact immediately."""
        self._assets.log_output(path, metadata=metadata)

    def log_temp(
        self, path: StrPath, metadata: Mapping[str, Any] | None = None
    ) -> None:
        """Log an existing temporary artifact immediately."""
        self._assets.log_temp(path, metadata=metadata)

    # endregion Assets

    # region Logging

    def get_other(self, name: str) -> Any:
        """Return one flattened metadata value."""
        return self._others.get_other(name)

    def log_other(self, name: str, value: Any) -> None:
        """Log one metadata value."""
        self._others.log_other(name, value)

    def get_others(self) -> dict[str, Any]:
        """Return logged metadata as a nested dictionary."""
        return self._others.get_others()

    def log_others(self, others: Mapping[str, Any]) -> None:
        """Log multiple metadata values."""
        self._others.log_others(others)

    def get_param(self, name: str) -> Any:
        """Return one flattened parameter value."""
        return self._params.get_param(name)

    def log_param(self, name: str, value: Any) -> None:
        """Log one parameter value."""
        self._params.log_param(name, value)

    def get_params(self) -> dict[str, Any]:
        """Return logged parameters as a nested dictionary."""
        return self._params.get_params()

    def log_params(self, params: Mapping[str, Any]) -> None:
        """Log multiple parameter values."""
        self._params.log_params(params)

    # endregion Logging

    def summary(self, prefix: StrPath | None = None) -> dict[str, Any]:
        """Build a JSON/YAML-friendly run summary.

        Args:
            prefix: Optional directory to strip from artifact paths.

        Returns:
            Run metadata, parameters, artifact paths, and user metadata.
        """
        summary: dict[str, Any] = {"name": self.run_name, "tags": self.tags}
        others: dict[str, Any] = self.get_others()
        summary.update(others.pop("cherries"))
        summary["params"] = self.get_params()
        summary.update(self._assets.summary.to_dict(prefix=prefix))
        summary["others"] = others
        return summary


def _strip_path(path: Path) -> Path:
    return Path(*filter(lambda p: p not in _PATH_SKIP_NAMES, path.parts))

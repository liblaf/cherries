from __future__ import annotations

import functools
import logging
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import attrs
import git
import git.exc
import liblaf.logging as _log
import tlz
from environs import env

from liblaf.cherries import utils
from liblaf.cherries.bundle import bundles, relative_or_absolute, relative_or_name

from ._manager import PluginManager, delegate
from ._typing import MethodName

if TYPE_CHECKING:
    from _typeshed import StrPath

logger: logging.Logger = logging.getLogger(__name__)

_PATH_SKIP_NAMES: set[str] = {"exp", "src"}


@attrs.define
class Run(PluginManager):
    """Mutable state for one Cherries experiment run.

    A run knows the entrypoint script, experiment folders, queued artifacts,
    current step, and registered plugins. Top-level functions such as
    [`output`][liblaf.cherries.output] forward to the process-global
    [`run`][liblaf.cherries.core.run] instance.

    Path helper methods only queue paths. Cherries flushes those queues from
    [`end`][liblaf.cherries.core.Run.end], skips missing files with a warning,
    and expands known artifact bundles such as VTK `.series` manifests.
    """

    _assets_queue: list[Path] = attrs.field(init=False, factory=list)
    _inputs_queue: list[Path] = attrs.field(init=False, factory=list)
    _outputs_queue: list[Path] = attrs.field(init=False, factory=list)
    _temps_queue: list[Path] = attrs.field(init=False, factory=list)

    @functools.cached_property
    def data_dir(self) -> Path:
        """Directory used by [`input`][liblaf.cherries.core.Run.input] and output paths."""
        return self.exp_dir / "data"

    @functools.cached_property
    def entrypoint(self) -> Path:
        """Resolved path to the script that started the process."""
        if sys.argv[0] == "-c":
            return Path(os.devnull).resolve()
        return Path(sys.argv[0]).resolve()

    @functools.cached_property
    def exp_dir(self) -> Path:
        """Experiment directory inferred from the entrypoint path."""
        parent: Path = self.entrypoint.parent
        while parent.name in _PATH_SKIP_NAMES:
            parent: Path = parent.parent
        return parent

    @functools.cached_property
    def exp_name(self) -> str:
        """Experiment name used by plugins and summaries."""
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
    def figs_dir(self) -> Path:
        """Conventional directory for generated figures."""
        return self.exp_dir / "figs"

    @functools.cached_property
    def logs_dir(self) -> Path:
        """Conventional directory for log files."""
        return self.exp_dir / "logs"

    @functools.cached_property
    def project_dir(self) -> Path:
        """Git working tree directory, or the current directory outside Git."""
        if self.repo is None:
            return Path.cwd().resolve()
        return Path(self.repo.working_dir).resolve()

    @functools.cached_property
    def project_name(self) -> str:
        """Project name inferred from the Git remote or project directory."""
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
        """Nearest Git repository, if the process is running inside one."""
        try:
            return git.Repo(search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as err:
            logger.warning("%s", err)
            return None

    @functools.cached_property
    def start_time(self) -> datetime:
        """Timezone-aware timestamp captured when first accessed."""
        return datetime.now().astimezone()

    @functools.cached_property
    def tags(self) -> list[str]:
        """Run tags from the `CHERRIES_TAGS` environment variable."""
        return env.list("CHERRIES_TAGS", [])

    @property
    def step(self) -> int | None:
        """Current experiment step reported by plugins."""
        return self.get_step()

    @step.setter
    def step(self, value: int | None) -> None:
        self.set_step(value)

    @functools.cached_property
    def temp_dir(self) -> Path:
        """Directory used by [`temp`][liblaf.cherries.core.Run.temp] paths."""
        return self.exp_dir / "temp"

    @property
    def url(self) -> str:
        """Run URL reported by the first plugin that provides one."""
        return self.get_url()

    def asset(self, path: StrPath, *, mkdir: bool = False) -> Path:
        """Queue an artifact path under the experiment directory.

        Args:
            path: Path relative to [`exp_dir`][liblaf.cherries.core.Run.exp_dir].
            mkdir: Create the parent directory before returning the path.

        Returns:
            Absolute path to the queued artifact.
        """
        absolute: Path = self.exp_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._assets_queue.append(absolute)
        return absolute

    def input(self, path: StrPath, *, mkdir: bool = False) -> Path:
        """Queue an input path under the experiment `data/` directory.

        Args:
            path: Path relative to [`data_dir`][liblaf.cherries.core.Run.data_dir].
            mkdir: Create the parent directory before returning the path.

        Returns:
            Absolute path to the queued input.
        """
        absolute: Path = self.data_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._inputs_queue.append(absolute)
        return absolute

    def output(self, path: StrPath, *, mkdir: bool = False) -> Path:
        """Queue an output path under the experiment `data/` directory.

        Args:
            path: Path relative to [`data_dir`][liblaf.cherries.core.Run.data_dir].
            mkdir: Create the parent directory before returning the path.

        Returns:
            Absolute path to the queued output.
        """
        absolute: Path = self.data_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._outputs_queue.append(absolute)
        return absolute

    def temp(self, path: StrPath, *, mkdir: bool = False) -> Path:
        """Queue a temporary artifact path under the experiment `temp/` directory.

        Args:
            path: Path relative to [`temp_dir`][liblaf.cherries.core.Run.temp_dir].
            mkdir: Create the parent directory before returning the path.

        Returns:
            Absolute path to the queued temporary artifact.
        """
        absolute: Path = self.temp_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._temps_queue.append(absolute)
        return absolute

    # region Spec

    def start(self, *args, **kwargs) -> None:
        """Start plugins and record Cherries run metadata."""
        __tracebackhide__ = True
        self.delegate("start", args, kwargs)
        entrypoint: Path = relative_or_absolute(self.entrypoint, self.project_dir)
        exp_dir: Path = relative_or_absolute(self.exp_dir, self.project_dir)
        self.log_other("cherries.entrypoint", entrypoint)
        self.log_other("cherries.exp_dir", exp_dir)
        self.log_other("cherries.start_time", self.start_time)

    def end(self, *args: Any, exc: BaseException | None = None, **kwargs: Any) -> None:
        """Flush queued artifacts and end plugins.

        Args:
            *args: Positional values forwarded to plugin `end` hooks.
            exc: Exception raised by the experiment, if any.
            **kwargs: Keyword values forwarded to plugin `end` hooks.
        """
        __tracebackhide__ = True
        self.log_other("cherries.end_time", datetime.now().astimezone())
        for path in self._assets_queue:
            self.log_asset(path)
        for path in self._inputs_queue:
            self.log_input(path)
        for path in self._outputs_queue:
            self.log_output(path)
        for path in self._temps_queue:
            self.log_temp(path)
        kwargs["exc"] = exc
        self.delegate("end", args, kwargs)

    @delegate(first_result=True)
    def get_other(self, name: str) -> Any:
        raise NotImplementedError

    @delegate
    def log_other(self, name: str, value: Any) -> None: ...

    @delegate(first_result=True)
    def get_others(self) -> Mapping[str, Any]:
        raise NotImplementedError

    @delegate
    def log_others(self, others: Mapping[str, Any]) -> None: ...

    @delegate(first_result=True)
    def get_param(self, name: str) -> Any:
        raise NotImplementedError

    @delegate
    def log_param(self, name: str, value: Any) -> None: ...

    @delegate(first_result=True)
    def get_params(self) -> Mapping[str, Any]:
        raise NotImplementedError

    @delegate
    def log_params(self, params: Mapping[str, Any]) -> None: ...

    @delegate(first_result=True)
    def get_step(self) -> int | None:
        raise NotImplementedError

    @delegate
    def set_step(self, step: int | None = None) -> None: ...

    @delegate
    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None: ...

    @delegate
    def log_metrics(
        self, metrics: Mapping[str, Any], step: int | None = None, **kwargs
    ) -> None: ...

    @delegate(first_result=True)
    def get_url(self) -> str:
        raise NotImplementedError

    def log_asset(self, path: StrPath, **kwargs) -> None:
        """Log an artifact relative to the experiment directory."""
        __tracebackhide__ = True
        self._log_asset(path, "log_asset", self.exp_dir, **kwargs)

    def log_input(self, path: StrPath, **kwargs) -> None:
        """Log an input artifact relative to the experiment `data/` directory."""
        __tracebackhide__ = True
        self._log_asset(path, "log_input", self.data_dir, **kwargs)

    def log_output(self, path: StrPath, **kwargs) -> None:
        """Log an output artifact relative to the experiment `data/` directory."""
        __tracebackhide__ = True
        self._log_asset(path, "log_output", self.data_dir, **kwargs)

    def log_temp(self, path: StrPath, **kwargs) -> None:
        """Log a temporary artifact relative to the experiment `temp/` directory."""
        __tracebackhide__ = True
        self._log_asset(path, "log_temp", self.temp_dir, **kwargs)

    # endregion Spec

    def _log_asset(
        self, path: StrPath, method_name: MethodName, prefix: StrPath, **kwargs
    ) -> None:
        """Delegate one asset and any bundle-discovered related files."""
        __tracebackhide__ = True
        path: Path = Path(path).resolve()
        if not path.exists():
            _log.warning("No such file or directory: %s", path)
            return
        prefix: Path = Path(prefix).resolve()
        name: Path = relative_or_name(path, prefix)
        self.delegate(method_name, args=(path, name), kwargs=kwargs)
        kwargs: dict[str, Any] = tlz.assoc(kwargs, "report", False)  # noqa: FBT003
        for absolute_, relative_, optional in bundles.ls_files(path, prefix):
            absolute: Path = Path(absolute_)
            relative: Path = Path(relative_)
            if not absolute.exists():
                if not optional:
                    _log.warning("No such file or directory: %s", absolute)
                continue
            self.delegate(method_name, args=(absolute, relative), kwargs=kwargs)

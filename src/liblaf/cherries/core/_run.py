from __future__ import annotations

import functools
import logging
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import attrs
import git
import git.exc
from liblaf.grapes.logging import autolog

from liblaf.cherries.bundle import bundles, relative_to_or_name
from liblaf.cherries.core._typing import MethodName

from ._plugin_manager import PluginManager, delegate

if TYPE_CHECKING:
    from _typeshed import StrPath

logger: logging.Logger = logging.getLogger(__name__)

_PATH_SKIP_NAMES: set[str] = {"exp", "src"}


@attrs.define
class Run(PluginManager):
    _assets_queue: list[Path] = attrs.field(init=False, factory=list)
    _inputs_queue: list[Path] = attrs.field(init=False, factory=list)
    _outputs_queue: list[Path] = attrs.field(init=False, factory=list)
    _temps_queue: list[Path] = attrs.field(init=False, factory=list)

    @functools.cached_property
    def data_dir(self) -> Path:
        return self.exp_dir / "data"

    @functools.cached_property
    def entrypoint(self) -> Path:
        if sys.argv[0] == "-c":
            return None  # pyright: ignore[reportReturnType]
        return Path(sys.argv[0]).resolve()

    @functools.cached_property
    def exp_dir(self) -> Path:
        parent: Path = self.entrypoint.parent
        while parent.name in _PATH_SKIP_NAMES:
            parent = parent.parent
        return parent

    @functools.cached_property
    def exp_name(self) -> str:
        name: str = self.entrypoint.relative_to(self.project_dir).as_posix()
        while True:
            original: str = name
            for folder in _PATH_SKIP_NAMES:
                name = name.removeprefix(f"{folder}/")
            if name == original:
                break
        return name

    @functools.cached_property
    def fig_dir(self) -> Path:
        return self.exp_dir / "fig"

    @functools.cached_property
    def logs_dir(self) -> Path:
        return self.exp_dir / "logs"

    @functools.cached_property
    def project_dir(self) -> Path:
        try:
            repo: git.Repo = git.Repo(search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as err:
            logger.warning("%s", err)
            return Path.cwd().resolve()
        else:
            return Path(repo.working_dir).resolve()

    @functools.cached_property
    def project_name(self) -> str:
        return self.project_dir.name

    @functools.cached_property
    def start_time(self) -> datetime:
        return datetime.now().astimezone()

    @functools.cached_property
    def temp_dir(self) -> Path:
        return self.exp_dir / "temp"

    @property
    def url(self) -> str:
        return self.get_url()

    def asset(self, path: StrPath, *, mkdir: bool = False) -> Path:
        absolute: Path = self.exp_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._assets_queue.append(absolute)
        return absolute

    def input(self, path: StrPath, *, mkdir: bool = False) -> Path:
        absolute: Path = self.data_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._inputs_queue.append(absolute)
        return absolute

    def output(self, path: StrPath, *, mkdir: bool = False) -> Path:
        absolute: Path = self.data_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._outputs_queue.append(absolute)
        return absolute

    def temp(self, path: StrPath, *, mkdir: bool = False) -> Path:
        absolute: Path = self.temp_dir / path
        if mkdir:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        self._temps_queue.append(absolute)
        return absolute

    def end(self, *args, **kwargs) -> None:
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
        self.delegate("end", args, kwargs)

    @delegate(first_result=True)
    def get_other(self, name: str) -> Any: ...

    @delegate(first_result=True)
    def get_others(self) -> Mapping[str, Any]: ...

    @delegate(first_result=True)
    def get_param(self, name: str) -> Any: ...

    @delegate(first_result=True)
    def get_params(self) -> Mapping[str, Any]: ...

    @delegate(first_result=True)
    def get_url(self) -> str: ...

    def log_asset(self, path: StrPath, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_asset", self.exp_dir, **kwargs)

    def log_input(self, path: StrPath, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_input", self.data_dir, **kwargs)

    def log_output(self, path: StrPath, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_output", self.data_dir, **kwargs)

    def log_temp(self, path: StrPath, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_temp", self.temp_dir, **kwargs)

    @delegate
    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None: ...

    @delegate
    def log_metrics(
        self, metrics: Mapping[str, Any], step: int | None = None, **kwargs
    ) -> None: ...

    @delegate
    def log_other(self, name: str, value: Any) -> None: ...

    @delegate
    def log_others(self, others: Mapping[str, Any]) -> None: ...

    @delegate
    def log_param(self, name: str, value: Any) -> None: ...

    @delegate
    def log_params(self, params: Mapping[str, Any]) -> None: ...

    @delegate
    def set_step(self, step: int | None = None) -> None: ...

    def start(self, *args, **kwargs) -> None:
        __tracebackhide__ = True
        self.delegate("start", args, kwargs)
        self.log_other(
            "cherries.entrypoint",
            _relative_or_absolute(self.entrypoint, self.project_dir),
        )
        self.log_other(
            "cherries.exp_dir", _relative_or_absolute(self.exp_dir, self.project_dir)
        )
        self.log_other("cherries.start_time", self.start_time)

    def _log_asset(
        self, path: StrPath, method_name: MethodName, prefix: StrPath, **kwargs
    ) -> None:
        __tracebackhide__ = True
        path: Path = Path(path).resolve()
        if not path.exists():
            autolog.warning("No such file or directory: %s", path)
            return
        prefix: Path = Path(prefix).resolve()
        name: StrPath = relative_to_or_name(path, prefix)
        self.delegate(method_name, args=(path, name), kwargs=kwargs)
        for absolute, relative, required in bundles.ls_files(path, prefix):
            absolute = Path(absolute)  # noqa: PLW2901
            relative = Path(relative)  # noqa: PLW2901
            if not absolute.exists():
                if required:
                    autolog.warning("No such file or directory: %s", absolute)
                continue
            self.delegate(method_name, args=(absolute, relative), kwargs=kwargs)


def _relative_or_absolute(path: Path, prefix: Path) -> Path:
    try:
        return path.relative_to(prefix)
    except ValueError:
        return path

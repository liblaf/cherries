import functools
import logging
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import attrs
import git
import git.exc
from liblaf.grapes.logging import depth_logger

from liblaf.cherries.bundle import bundles
from liblaf.cherries.core._typing import MethodName

from ._plugin_manager import PluginManager, delegate

type PathLike = str | os.PathLike[str]

logger: logging.Logger = logging.getLogger(__name__)

_PATH_SKIP_NAMES: set[str] = {"exp", "src"}


@attrs.define
class Run(PluginManager):
    @functools.cached_property
    def data_dir(self) -> Path:
        return self.exp_dir / "data"

    @functools.cached_property
    def entrypoint(self) -> Path:
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

    @delegate
    def end(self, *args, **kwargs) -> None: ...

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

    def log_asset(self, path: PathLike, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_asset", self.exp_dir, **kwargs)

    def log_input(self, path: PathLike, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_input", self.data_dir, **kwargs)

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

    def log_output(self, path: PathLike, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_output", self.data_dir, **kwargs)

    @delegate
    def log_param(self, name: str, value: Any) -> None: ...

    @delegate
    def log_params(self, params: Mapping[str, Any]) -> None: ...

    def log_temp(self, path: PathLike, **kwargs) -> None:
        __tracebackhide__ = True
        self._log_asset(path, "log_temp", self.temp_dir, **kwargs)

    @delegate
    def set_step(self, step: int | None = None) -> None: ...

    @delegate
    def start(self, *args, **kwargs) -> None: ...

    def _log_asset(
        self, path: PathLike, method_name: MethodName, prefix: PathLike, **kwargs
    ) -> None:
        __tracebackhide__ = True
        for p, relative, required in bundles.ls_files(path, prefix):
            p = Path(p)  # noqa: PLW2901
            relative = Path(relative)  # noqa: PLW2901
            if required and not p.exists():
                depth_logger.warning("No such file or directory: %s", p)
                continue
            self.delegate(method_name, args=(p, relative), kwargs=kwargs)

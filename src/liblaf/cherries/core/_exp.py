import datetime
import functools
from pathlib import Path
from typing import Any

from liblaf.cherries import pathutils as _path
from liblaf.cherries.typed import PathLike

from ._spec import Plugin, spec


class Experiment(Plugin):
    @functools.cached_property
    def exp_dir(self) -> Path:
        return _path.exp_dir(absolute=True)

    @property
    def exp_id(self) -> str:
        return self.get_exp_id()

    @property
    def exp_name(self) -> str:
        return self.get_exp_name()

    @exp_name.setter
    def exp_name(self, value: str) -> None:
        self.set_exp_name(value)

    @property
    def exp_url(self) -> str:
        return self.get_exp_url()

    @property
    def project_id(self) -> str:
        return self.get_project_id()

    @property
    def project_name(self) -> str:
        return self.get_project_name()

    @functools.cached_property
    def start_time(self) -> datetime.datetime:
        return datetime.datetime.now().astimezone()

    def log_input(self, path: PathLike, /, **kwargs) -> None:
        self.log_asset(path, prefix="inputs/", **kwargs)

    def log_output(self, path: PathLike, /, **kwargs) -> None:
        self.log_asset(path, prefix="outputs/", **kwargs)

    @spec
    def add_tag(self, tag: str, /) -> None: ...

    @spec
    def add_tags(self, tags: list[str], /) -> None: ...

    @spec
    def end(self) -> None: ...

    @spec(firstresult=True)
    def get_exp_id(self) -> str: ...

    @spec(firstresult=True)
    def get_exp_name(self) -> str: ...

    @spec(firstresult=True)
    def get_exp_url(self) -> str: ...

    @spec(firstresult=True)
    def get_project_id(self) -> str: ...

    @spec(firstresult=True)
    def get_project_name(self) -> str: ...

    @spec(firstresult=True)
    def get_project_url(self) -> str: ...

    @spec
    def log_asset(self, path: PathLike, /, prefix: str | None = None) -> None: ...

    @spec
    def log_code(self, path: str, /) -> None: ...

    @spec
    def log_metric(
        self,
        key: str,
        value: float,
        /,
        step: int | None = None,
        epoch: int | None = None,
    ) -> None: ...

    @spec
    def log_metrics(
        self,
        metrics: dict[str, float],
        /,
        step: int | None = None,
        epoch: int | None = None,
    ) -> None: ...

    @spec
    def log_other(self, key: str, value: Any, /) -> None: ...

    @spec
    def log_others(self, others: dict[str, Any], /) -> None: ...

    @spec
    def log_param(self, key: str, value: Any, /) -> None: ...

    @spec
    def log_params(self, params: dict[str, Any], /) -> None: ...

    @spec
    def set_exp_name(self, name: str, /) -> None: ...

    @spec
    def start(self) -> None: ...

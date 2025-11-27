from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import attrs

from ._plugin import Plugin

if TYPE_CHECKING:
    from ._run import Run


@attrs.define
class PluginSchema(Plugin):
    @property
    def run(self) -> Run:
        return self.manager  # pyright: ignore[reportReturnType]

    def end(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def get_other(self, name: str) -> Any:
        raise NotImplementedError

    def get_others(self) -> Mapping[str, Any]:
        raise NotImplementedError

    def get_param(self, name: str) -> Any:
        raise NotImplementedError

    def get_params(self) -> Mapping[str, Any]:
        raise NotImplementedError

    def get_url(self) -> str:
        raise NotImplementedError

    def log_asset(self, path: Path, name: Path, **kwargs) -> None:
        raise NotImplementedError

    def log_input(self, path: Path, name: Path, **kwargs) -> None:
        raise NotImplementedError

    def log_metric(
        self, name: str, value: Any, step: int | None = None, **kwargs
    ) -> None:
        raise NotImplementedError

    def log_metrics(
        self, metrics: Mapping[str, Any], step: int | None = None, **kwargs
    ) -> None:
        raise NotImplementedError

    def log_other(self, name: str, value: Any) -> None:
        raise NotImplementedError

    def log_others(self, others: Mapping[str, Any]) -> None:
        raise NotImplementedError

    def log_output(self, path: Path, name: Path, **kwargs) -> None:
        raise NotImplementedError

    def log_param(self, name: str, value: Any) -> None:
        raise NotImplementedError

    def log_params(self, params: Mapping[str, Any]) -> None:
        raise NotImplementedError

    def log_temp(self, path: Path, name: Path, **kwargs) -> None:
        raise NotImplementedError

    def set_step(self, step: int | None = None) -> None:
        raise NotImplementedError

    def start(self, *args, **kwargs) -> None:
        raise NotImplementedError

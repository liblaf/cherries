from __future__ import annotations

import bisect
import enum
import functools
import operator
from collections.abc import Iterable
from pathlib import Path
from typing import Any, override

import attrs
import mlflow
import mlflow.entities
from loguru import logger

from liblaf.cherries import pathutils as _path
from liblaf.cherries.typed import PathLike


class RunStatus(enum.StrEnum):
    FAILED = mlflow.entities.RunStatus.to_string(mlflow.entities.RunStatus.FAILED)
    FINISHED = mlflow.entities.RunStatus.to_string(mlflow.entities.RunStatus.FINISHED)
    KILLED = mlflow.entities.RunStatus.to_string(mlflow.entities.RunStatus.KILLED)


@functools.total_ordering
@attrs.define
class Plugin[**P, T]:
    priority: int = attrs.field(default=0, kw_only=True, eq=True, order=True)
    _children: list[Plugin] = attrs.field(
        factory=list, eq=False, order=False, alias="children"
    )

    def __attrs_post_init__(self) -> None:
        self._children.sort(key=operator.attrgetter("priority"))

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        ret: T | None = None
        for child in self._children:
            try:
                ret = child(*args, **kwargs)
            except BaseException as err:
                if isinstance(err, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.exception(child)
        return ret  # pyright: ignore[reportReturnType]

    def __lt__(self, other: Plugin) -> bool:
        if not isinstance(other, Plugin):
            return NotImplemented
        return self.priority < other.priority

    def __eq__(self, other: Plugin) -> bool:  # pyright: ignore[reportIncompatibleMethodOverride]
        if not isinstance(other, Plugin):
            return NotImplemented
        return self.priority == other.priority

    @property
    def children(self) -> list[Plugin]:
        return self._children

    def add(self, *child: Plugin) -> None:
        for c in child:
            bisect.insort(self._children, c, key=operator.attrgetter("priority"))

    def extend(self, children: Iterable[Plugin]) -> None:
        self.add(*children)

    def remove(self, child: Plugin) -> None:
        self._children.remove(child)


@attrs.define
class End(Plugin):
    @override
    def __call__(self, status: RunStatus = RunStatus.FINISHED) -> None:
        return super().__call__(status)


@attrs.define
class LogArtifact(Plugin):
    @override
    def __call__(
        self, local_path: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> Path:
        ret: Path | None = super().__call__(local_path, artifact_path, **kwargs)
        if ret is None:
            ret = _path.as_path(local_path)
        return ret


@attrs.define
class LogArtifacts(Plugin):
    @override
    def __call__(
        self, local_dir: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> Path:
        ret: Path | None = super().__call__(local_dir, artifact_path, **kwargs)
        if ret is None:
            ret = _path.as_path(local_dir)
        return ret


@attrs.define
class LogMetric(Plugin):
    @override
    def __call__(
        self, key: str, value: float, step: int | None = None, **kwargs
    ) -> None:
        return super().__call__(key, value, step, **kwargs)


@attrs.define
class LogParam(Plugin):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        return super().__call__(key, value, **kwargs)


@attrs.define
class SetTag(Plugin):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        return super().__call__(key, value, **kwargs)


@attrs.define
class Start(Plugin):
    @override
    def __call__(self) -> None:
        return super().__call__()

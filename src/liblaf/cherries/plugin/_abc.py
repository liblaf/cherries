from __future__ import annotations

import bisect
from collections.abc import Iterable
from typing import Any, Protocol, override

import attrs
from loguru import logger

from liblaf.cherries.typed import PathLike


@attrs.define(eq=True, order=True)
class Plugin[**P, T](Protocol):
    priority: int = attrs.field(default=0, kw_only=True, eq=True, order=True)
    _children: list[Plugin] = attrs.field(
        factory=list, eq=False, order=False, alias="children"
    )

    def __attrs_post_init__(self) -> None:
        self._children.sort()

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        ret: T | None = None
        for child in self._children:
            try:
                ret = child(*args, **kwargs)
            except AttributeError:
                logger.exception(child)
        return ret  # pyright: ignore[reportReturnType]

    @property
    def children(self) -> list[Plugin]:
        return self._children

    def add(self, *child: Plugin) -> None:
        for c in child:
            bisect.insort(self._children, c)

    def extend(self, children: Iterable[Plugin]) -> None:
        self.add(*children)

    def remove(self, child: Plugin) -> None:
        self._children.remove(child)


@attrs.define(eq=True, order=True)
class End(Plugin):
    @override
    def __call__(self) -> None:
        return super()()


@attrs.define(eq=True, order=True)
class LogArtifact(Plugin):
    @override
    def __call__(
        self, local_path: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> None:
        return super()(local_path, artifact_path, **kwargs)


@attrs.define(eq=True, order=True)
class LogArtifacts(Plugin):
    @override
    def __call__(
        self, local_dir: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> None:
        return super()(local_dir, artifact_path, **kwargs)


@attrs.define(eq=True, order=True)
class LogMetric(Plugin):
    @override
    def __call__(
        self, key: str, value: float, step: int | None = None, **kwargs
    ) -> None:
        return super()(key, value, step, **kwargs)


@attrs.define(eq=True, order=True)
class LogParam(Plugin):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        return super()(key, value, **kwargs)


@attrs.define(eq=True, order=True)
class SetTag(Plugin):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        return super()(key, value, **kwargs)


@attrs.define(eq=True, order=True)
class Start(Plugin):
    @override
    def __call__(self) -> None:
        return super()()

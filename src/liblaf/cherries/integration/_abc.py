import bisect
import functools
import operator
from collections.abc import Iterable, Mapping
from typing import Any

import attrs
from loguru import logger

from liblaf.cherries.typed import PathLike


@attrs.define
@functools.total_ordering
class Plugin[**P, T]:
    priority: int = attrs.field(default=0, kw_only=True)
    _children: list["Plugin"] = attrs.field(
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

    def __lt__(self, other: "Plugin") -> bool:
        if not isinstance(other, Plugin):
            return NotImplemented
        return self.priority < other.priority

    def __eq__(self, other: "Plugin") -> bool:  # pyright: ignore[reportIncompatibleMethodOverride]
        if not isinstance(other, Plugin):
            return NotImplemented
        return self.priority == other.priority

    @property
    def children(self) -> list["Plugin"]:
        return self._children

    def add(self, *children: "Plugin") -> None:
        for c in children:
            bisect.insort(self._children, c, key=operator.attrgetter("priority"))

    def extend(self, children: Iterable["Plugin"]) -> None:
        self.add(*children)

    def remove(self, child: "Plugin") -> None:
        self._children.remove(child)


@attrs.define
class AddTag(Plugin):
    def __call__(self, tag: str, /, **kwargs) -> None:
        super().__call__(tag, **kwargs)


@attrs.define
class AddTags(Plugin):
    def __call__(self, tags: Iterable[str], /, **kwargs) -> None:
        super().__call__(tags, **kwargs)


@attrs.define
class End(Plugin):
    def __call__(self, **kwargs) -> None:
        super().__call__(**kwargs)


@attrs.define
class LogAsset(Plugin):
    def __call__(self, path: PathLike, /, prefix: str | None = None, **kwargs) -> None:
        super().__call__(path, prefix=prefix, **kwargs)


@attrs.define
class LogCode(Plugin):
    def __call__(self, path: PathLike, /, **kwargs) -> None:
        super().__call__(path, **kwargs)


@attrs.define
class LogMetric(Plugin):
    def __call__(
        self,
        key: str,
        value: float,
        /,
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None:
        super().__call__(key, value, step=step, epoch=epoch, **kwargs)


@attrs.define
class LogMetrics(Plugin):
    def __call__(
        self,
        metrics: Mapping[str, Any],
        /,
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None:
        super().__call__(metrics, step=step, epoch=epoch, **kwargs)


@attrs.define
class LogOther(Plugin):
    def __call__(self, key: str, value: Any, /, **kwargs) -> None:
        super().__call__(key, value, **kwargs)


@attrs.define
class LogOthers(Plugin):
    def __call__(self, others: Mapping[str, Any], /, **kwargs) -> None:
        super().__call__(others, **kwargs)


@attrs.define
class LogParam(Plugin):
    def __call__(self, name: str, value: Any, /, **kwargs) -> None:
        super().__call__(name, value, **kwargs)


@attrs.define
class LogParams(Plugin):
    def __call__(self, params: Mapping[str, Any], /, **kwargs) -> None:
        super().__call__(params, **kwargs)


@attrs.define
class Start(Plugin):
    def __call__(self, **kwargs) -> None:
        super().__call__(**kwargs)

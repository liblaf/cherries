from collections.abc import Sequence
from typing import Protocol, get_type_hints

from liblaf import cherries


class MainFunction[T: cherries.BaseConfig](Protocol):
    def __call__(self, cfg: T) -> None: ...


def run[T: cherries.BaseConfig](
    main: MainFunction[T],
    *,
    backend: cherries.Backend | None = None,
    enabled: bool | None = None,
    plugins: Sequence[cherries.Plugin] | None = None,
) -> None:
    exp: cherries.Experiment = cherries.start(
        backend=backend, enabled=enabled, plugins=plugins
    )
    type_hints: dict[str, type[T]] = get_type_hints(main)
    cls: type[T] = next(iter(type_hints.values()))
    cfg: T = cls()
    exp.log_other("cherries/config", cfg)
    main(cfg)
    exp.end()

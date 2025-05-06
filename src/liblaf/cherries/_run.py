from collections.abc import Callable
from typing import get_type_hints

import pydantic

from liblaf.cherries import plugin, presets


def run[C: pydantic.BaseModel, T](main: Callable[[C], T]) -> T:
    run: plugin.Run = presets.default()
    type_hints: dict[str, type[C]] = get_type_hints(main)
    cls: type[C] = next(iter(type_hints.values()))
    cfg: C = cls()
    run.log_param("cherries.config", cfg.model_dump(mode="json"))
    ret: T = main(cfg)
    run.end()
    return ret

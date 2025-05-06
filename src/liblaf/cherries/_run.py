from collections.abc import Callable
from typing import get_type_hints

import pydantic

from liblaf.cherries import pathutils as _path
from liblaf.cherries import plugin, presets


def run[C: pydantic.BaseModel, T](main: Callable[[C], T]) -> T:
    run: plugin.Run = start()
    type_hints: dict[str, type[C]] = get_type_hints(main)
    cls: type[C] = next(iter(type_hints.values()))
    cfg: C = cls()
    run.log_param("cherries.config", cfg.model_dump(mode="json"))
    try:
        ret: T = main(cfg)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            run.end("KILLED")
            raise
        run.end("FAILED")
        raise
    else:
        run.end()
        return ret


def start() -> plugin.Run:
    run: plugin.Run = presets.default()
    run.start()
    run.log_src(_path.entrypoint(absolute=True))
    run.set_tag("cherries.entrypoint", _path.entrypoint(absolute=False))
    run.set_tag("cherries.exp-dir", _path.exp_dir(absolute=False))
    return plugin.run


def end() -> None:
    plugin.run.end()

from collections.abc import Callable
from typing import get_type_hints

import pydantic

from liblaf.cherries import config, integration, presets
from liblaf.cherries import pathutils as _path


def run[C: pydantic.BaseModel, T](
    main: Callable[[], T] | Callable[[C], T],
    *,
    play: bool = False,
    preset: presets.Preset = presets.default,
) -> T:
    exp: integration.Experiment = start(preset=preset, play=play)
    type_hints: dict[str, type[C]] = get_type_hints(main)
    del type_hints["return"]
    args: list[C] = []
    if len(type_hints) == 1:
        cls: type[C] = next(iter(type_hints.values()))
        cfg: C = cls()
        args.append(cfg)
        for path in config.get_inputs(cfg):
            exp.log_input(path)
    try:
        result: T = main(*args)
    finally:
        if len(type_hints) == 1:
            cfg: C = args[0]
            for path in config.get_outputs(cfg):
                exp.log_output(path)
        exp.end()
    return result


def start(
    preset: presets.Preset = presets.default, *, play: bool = False
) -> integration.Experiment:
    if play:
        preset = presets.playground
    exp: integration.Experiment = preset(integration.exp)
    exp.start()
    exp.log_other("cherries.entrypoint", _path.entrypoint(absolute=False))
    exp.log_other("cherries.exp-dir", _path.exp_dir(absolute=False))
    exp.log_other("cherries.start-time", exp.start_time)
    return exp


def end() -> None:
    integration.exp.end()

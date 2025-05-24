from collections.abc import Callable

from liblaf.cherries import integration

type Preset = Callable[[integration.Experiment], integration.Experiment]

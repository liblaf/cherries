from typing import override

import comet_ml

from liblaf.cherries import core


class Comet(core.Run):
    _exp: comet_ml.CometExperiment

    @property
    def exp(self) -> comet_ml.CometExperiment:
        return self._exp

    @override
    @core.impl(after=("Logging",))
    def end(self, *args, **kwargs) -> None:
        return self._exp.end()

    @override
    @core.impl(after=("Logging",))
    def start(self, *args, **kwargs) -> None:
        self._exp = comet_ml.start()

from typing import override

import comet_ml

from liblaf.cherries import core


class Comet(core.Run):
    _exp: comet_ml.CometExperiment

    @property
    def exp(self) -> comet_ml.CometExperiment:
        return self._exp

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        self._exp = comet_ml.start()

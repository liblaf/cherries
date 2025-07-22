from typing import override

import comet_ml

from liblaf.cherries import core


class Comet(core.Run):
    exp: comet_ml.CometExperiment

    @override
    @core.impl(after=("Logging",))
    def end(self, *args, **kwargs) -> None:
        return self.exp.end()

    @override
    @core.impl
    def get_url(self) -> str:
        return self.exp.url  # pyright: ignore[reportReturnType]

    @override
    @core.impl
    def log_metric(self, *args, **kwargs) -> None:
        return self.exp.log_metric(*args, **kwargs)

    @override
    @core.impl
    def log_metrics(self, *args, **kwargs) -> None:
        return self.exp.log_metrics(*args, **kwargs)

    @override
    @core.impl
    def log_other(self, *args, **kwargs) -> None:
        return self.exp.log_other(*args, **kwargs)

    @override
    @core.impl
    def log_others(self, *args, **kwargs) -> None:
        return self.exp.log_others(*args, **kwargs)

    @override
    @core.impl
    def log_parameter(self, *args, **kwargs) -> None:
        return self.exp.log_parameter(*args, **kwargs)

    @override
    @core.impl
    def log_parameters(self, *args, **kwargs) -> None:
        return self.exp.log_parameters(*args, **kwargs)

    @override
    @core.impl(after=("Logging",))
    def start(self, *args, **kwargs) -> None:
        self.exp = comet_ml.start()

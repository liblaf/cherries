import datetime
import functools
from os import PathLike
from pathlib import Path

import attrs
import comet_ml as comet

from liblaf.cherries import pathutils as _path

from ._abc import (
    AddTag,
    AddTags,
    End,
    LogAsset,
    LogCode,
    LogMetric,
    LogMetrics,
    LogOther,
    LogOthers,
    LogParam,
    LogParams,
    Start,
)


@attrs.define
class Experiment:
    add_tag: AddTag = attrs.field(factory=AddTag, init=False)
    add_tags: AddTags = attrs.field(factory=AddTags, init=False)
    end: End = attrs.field(factory=End, init=False)
    log_asset: LogAsset = attrs.field(factory=LogAsset, init=False)
    log_code: LogCode = attrs.field(factory=LogCode, init=False)
    log_metric: LogMetric = attrs.field(factory=LogMetric, init=False)
    log_metrics: LogMetrics = attrs.field(factory=LogMetrics, init=False)
    log_other: LogOther = attrs.field(factory=LogOther, init=False)
    log_others: LogOthers = attrs.field(factory=LogOthers, init=False)
    log_param: LogParam = attrs.field(factory=LogParam, init=False)
    log_params: LogParams = attrs.field(factory=LogParams, init=False)
    start: Start = attrs.field(factory=Start, init=False)

    @property
    def comet(self) -> comet.CometExperiment:
        return comet.get_running_experiment()  # pyright: ignore[reportReturnType]

    @functools.cached_property
    def exp_dir(self) -> Path:
        return _path.exp_dir(absolute=True)

    @property
    def exp_key(self) -> str:
        return self.comet.get_key()

    @property
    def exp_name(self) -> str:
        return self.comet.get_name()

    @exp_name.setter
    def exp_name(self, value: str) -> None:
        self.comet.set_name(value)

    @property
    def exp_url(self) -> str:
        return self.comet.url  # pyright: ignore[reportReturnType]

    @property
    def project_id(self) -> str:
        return self.comet.project_id  # pyright: ignore[reportReturnType]

    @property
    def project_name(self) -> str:
        return self.comet.project_name

    @functools.cached_property
    def start_time(self) -> datetime.datetime:
        return datetime.datetime.now().astimezone()

    def log_input(self, path: PathLike, /, **kwargs) -> None:
        self.log_asset(path, prefix="inputs/", **kwargs)

    def log_output(self, path: PathLike, /, **kwargs) -> None:
        self.log_asset(path, prefix="outputs/", **kwargs)


exp = Experiment()
add_tag: AddTag = exp.add_tag
add_tags: AddTags = exp.add_tags
end: End = exp.end
log_asset: LogAsset = exp.log_asset
log_code: LogCode = exp.log_code
log_metric: LogMetric = exp.log_metric
log_metrics: LogMetrics = exp.log_metrics
log_other: LogOther = exp.log_other
log_others: LogOthers = exp.log_others
log_param: LogParam = exp.log_param
log_params: LogParams = exp.log_params
start: Start = exp.start

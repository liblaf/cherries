from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, override
from unittest import mock

import attrs
import comet_ml as comet
from loguru import logger

from liblaf.cherries import meta
from liblaf.cherries.typed import PathLike

from . import _abc


class Comet:
    @property
    def exp(self) -> comet.CometExperiment:
        exp: comet.CometExperiment | None = comet.get_running_experiment()
        if exp is None:
            exp = mock.MagicMock()
        return exp


@attrs.define
class AddTag(Comet, _abc.AddTag):
    @override
    def __call__(self, tag: str, **kwargs) -> None:
        self.exp.add_tag(tag)


@attrs.define
class AddTags(Comet, _abc.AddTags):
    @override
    def __call__(self, tags: Iterable[str], **kwargs) -> None:
        self.exp.add_tags(list(tags))


@attrs.define
class End(Comet, _abc.End):
    @override
    def __call__(self, **kwargs) -> None:
        comet.end()


@attrs.define
class LogAsset(Comet, _abc.LogAsset):
    @override
    def __call__(self, path: PathLike, prefix: str | None = None, **kwargs) -> None:
        path = Path(path)
        if (dvc_path := path.with_name(path.name + ".dvc")).exists():
            path = dvc_path
        if path.is_file():
            filename: str | None = f"{prefix}/{path.name}" if prefix else None
            self.exp.log_asset(path, file_name=filename, **kwargs)
        elif path.is_dir():
            self.exp.log_asset_folder(str(path), **kwargs)
        else:
            logger.warning("Neither file nor directory: {}", path)


@attrs.define
class LogCode(Comet, _abc.LogCode):
    @override
    def __call__(self, path: PathLike, **kwargs) -> None:
        path = Path(path)
        if path.is_file():
            self.exp.log_code(str(path), **kwargs)
        elif path.is_dir():
            self.exp.log_code(folder=str(path), **kwargs)
        else:
            logger.warning("Neither file nor directory: {}", path)


@attrs.define
class LogMetric(Comet, _abc.LogMetric):
    @override
    def __call__(
        self,
        name: str,
        value: float,
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None:
        self.exp.log_metric(name, value, step=step, epoch=epoch)


@attrs.define
class LogMetrics(Comet, _abc.LogMetrics):
    @override
    def __call__(
        self,
        metrics: Mapping[str, Any],
        step: int | None = None,
        epoch: int | None = None,
        **kwargs,
    ) -> None:
        self.exp.log_metrics(metrics, step=step, epoch=epoch)  # pyright: ignore[reportArgumentType]


@attrs.define
class LogOther(Comet, _abc.LogOther):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        self.exp.log_other(key, value)


@attrs.define
class LogOthers(Comet, _abc.LogOthers):
    @override
    def __call__(self, others: Mapping[str, Any], **kwargs) -> None:
        self.exp.log_others(others)  # pyright: ignore[reportArgumentType]


@attrs.define
class LogParam(Comet, _abc.LogParam):
    @override
    def __call__(self, name: str, value: Any, **kwargs) -> None:
        self.exp.log_parameter(name, value)


@attrs.define
class LogParams(Comet, _abc.LogParams):
    @override
    def __call__(self, params: Any, **kwargs: Any) -> None:
        self.exp.log_parameters(params)


@attrs.define
class Start(Comet, _abc.Start):
    text: bool = True
    jsonl: bool = False

    @override
    def __call__(self, **kwargs) -> None:
        comet.start(
            project_name=meta.project_name(),
            experiment_config=comet.ExperimentConfig(
                auto_output_logging="native", name=meta.exp_name()
            ),
        )

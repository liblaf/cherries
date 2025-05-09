from pathlib import Path
from typing import Any, override

import attrs
import mlflow

from liblaf.cherries import info as _info
from liblaf.cherries import pathutils as _path
from liblaf.cherries.typed import PathLike

from ._abc import (
    End,
    LogArtifact,
    LogArtifacts,
    LogMetric,
    LogParam,
    RunStatus,
    SetTag,
    Start,
)


@attrs.define
class MlflowEnd(End):
    @override
    def __call__(self, status: RunStatus = RunStatus.FINISHED) -> None:
        mlflow.end_run(status)


@attrs.define
class MlflowLogArtifact(LogArtifact):
    @override
    def __call__(
        self, local_path: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> Path:
        local_path: Path = _path.as_path(local_path)
        if (dvc_file := local_path.with_name(local_path.name + ".dvc")).is_file():
            local_path = dvc_file
        mlflow.log_artifact(
            _path.as_os_path(local_path), _path.as_posix(artifact_path), **kwargs
        )
        return _path.as_path(local_path)


@attrs.define
class MlflowLogArtifacts(LogArtifacts):
    @override
    def __call__(
        self, local_dir: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> Path:
        local_dir: Path = _path.as_path(local_dir)
        if (dvc_file := local_dir.with_name(local_dir.name + ".dvc")).is_file():
            local_dir = dvc_file
        mlflow.log_artifact(
            _path.as_os_path(local_dir), _path.as_posix(artifact_path), **kwargs
        )
        return _path.as_path(local_dir)


@attrs.define
class MlflowLogParam(LogParam):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        mlflow.log_param(key, value, **kwargs)


@attrs.define
class MlflowLogMetric(LogMetric):
    @override
    def __call__(
        self, key: str, value: float, step: int | None = None, **kwargs
    ) -> None:
        mlflow.log_metric(key, value, step, **kwargs)


@attrs.define
class MlflowSetTag(SetTag):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        mlflow.set_tag(key, value, **kwargs)


@attrs.define
class MlflowStart(Start):
    @override
    def __call__(self) -> None:
        mlflow.set_experiment(_info.exp_name())
        mlflow.start_run(run_name=_info.run_name())

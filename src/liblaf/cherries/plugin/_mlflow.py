from typing import Any, override

import attrs
import mlflow

from liblaf.cherries import path as _path
from liblaf.cherries.typed import PathLike

from ._abc import End, LogArtifact, LogArtifacts, LogMetric, LogParam, SetTag, Start


@attrs.define(eq=True, order=True)
class MlflowEnd(End):
    @override
    def __call__(self) -> None:
        mlflow.end_run()


@attrs.define(eq=True, order=True)
class MlflowLogArtifact(LogArtifact):
    @override
    def __call__(
        self, local_path: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> None:
        mlflow.log_artifact(
            _path.as_os_path(local_path), _path.as_posix(artifact_path), **kwargs
        )


@attrs.define(eq=True, order=True)
class MlflowLogArtifacts(LogArtifacts):
    @override
    def __call__(
        self, local_dir: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> None:
        mlflow.log_artifact(
            _path.as_os_path(local_dir), _path.as_posix(artifact_path), **kwargs
        )


@attrs.define(eq=True, order=True)
class MlflowLogParam(LogParam):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        mlflow.log_param(key, value, **kwargs)


@attrs.define(eq=True, order=True)
class MlflowLogMetric(LogMetric):
    @override
    def __call__(
        self, key: str, value: float, step: int | None = None, **kwargs
    ) -> None:
        mlflow.log_metric(key, value, step, **kwargs)


@attrs.define(eq=True, order=True)
class MlflowSetTag(SetTag):
    @override
    def __call__(self, key: str, value: Any, **kwargs) -> None:
        mlflow.set_tag(key, value, **kwargs)


@attrs.define(eq=True, order=True)
class MlflowStart(Start):
    @override
    def __call__(self) -> None:
        mlflow.start_run()

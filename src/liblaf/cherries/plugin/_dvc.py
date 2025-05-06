import subprocess as sp
from pathlib import Path
from typing import override

import attrs

from liblaf.cherries import path as _path
from liblaf.cherries.typed import PathLike

from ._abc import End, LogArtifact, LogArtifacts


class DvcEnd(End):
    @override
    def __call__(self) -> None:
        sp.run(["dvc", "status"], check=True)
        sp.run(["dvc", "push"], check=True)


@attrs.define(eq=True, order=True)
class DvcLogArtifact(LogArtifact):
    @override
    def __call__(
        self, local_path: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> None:
        local_path: Path = _path.as_path(local_path)
        sp.run(["dvc", "add", local_path], check=True)


@attrs.define(eq=True, order=True)
class DvcLogArtifacts(LogArtifacts):
    @override
    def __call__(
        self, local_dir: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> None:
        local_dir: Path = _path.as_path(local_dir)
        sp.run(["dvc", "add", local_dir], check=True)

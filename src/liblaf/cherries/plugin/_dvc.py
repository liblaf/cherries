import subprocess as sp
from pathlib import Path
from typing import override

import attrs

from liblaf.cherries import pathutils as _path
from liblaf.cherries.typed import PathLike

from ._abc import End, LogArtifact, LogArtifacts, RunStatus


@attrs.define
class DvcEnd(End):
    @override
    def __call__(self, status: RunStatus = RunStatus.FINISHED) -> None:
        sp.run(["dvc", "status"], check=True)
        sp.run(["dvc", "push"], check=True)


@attrs.define
class DvcLogArtifact(LogArtifact):
    @override
    def __call__(
        self, local_path: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> Path:
        local_path: Path = _path.as_path(local_path)
        sp.run(["dvc", "add", local_path], check=False)
        return local_path


@attrs.define
class DvcLogArtifacts(LogArtifacts):
    @override
    def __call__(
        self, local_dir: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> Path:
        local_dir: Path = _path.as_path(local_dir)
        sp.run(["dvc", "add", local_dir], check=False)
        return local_dir


def check_ignore(local_path: PathLike) -> bool:
    proc: sp.CompletedProcess[bytes] = sp.run(
        ["dvc", "check-ignore", local_path], check=False
    )
    return proc.returncode == 0

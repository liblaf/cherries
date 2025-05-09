import subprocess as sp
from pathlib import Path
from typing import override

import attrs
import git
import git.exc

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
        if check_ignore(local_path) or tracked_by_git(local_path):
            return local_path
        sp.run(["dvc", "add", local_path], check=True)
        return local_path


@attrs.define
class DvcLogArtifacts(LogArtifacts):
    @override
    def __call__(
        self, local_dir: PathLike, artifact_path: PathLike | None = None, **kwargs
    ) -> Path:
        local_dir: Path = _path.as_path(local_dir)
        if check_ignore(local_dir) or tracked_by_git(local_dir):
            return local_dir
        sp.run(["dvc", "add", local_dir], check=True)
        return local_dir


def check_ignore(local_path: PathLike) -> bool:
    proc: sp.CompletedProcess[bytes] = sp.run(
        ["dvc", "check-ignore", local_path], check=False
    )
    return proc.returncode == 0


def tracked_by_git(local_path: PathLike) -> bool:
    local_path: Path = _path.as_path(local_path).absolute()
    try:
        repo = git.Repo(search_parent_directories=True)
        repo.git.ls_files(local_path, error_unmatch=True)
    except git.exc.GitCommandError:
        return False
    return True

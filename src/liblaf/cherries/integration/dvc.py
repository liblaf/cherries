import subprocess as sp
from pathlib import Path
from typing import override

import attrs
import git
import git.exc

from liblaf.cherries import pathutils as _path
from liblaf.cherries.typed import PathLike

from . import _abc


@attrs.define
class End(_abc.End):
    priority: int = attrs.field(default=-2, kw_only=True)  # after logging

    @override
    def __call__(self, **kwargs) -> None:
        sp.run(["dvc", "status"], check=True)
        sp.run(["dvc", "push"], check=True)


@attrs.define
class LogAsset(_abc.LogAsset):
    priority: int = attrs.field(default=-1, kw_only=True)  # before Comet

    @override
    def __call__(self, path: PathLike, prefix: str | None = None, **kwargs) -> None:
        path: Path = _path.as_path(path)
        if check_ignore(path) or tracked_by_git(path):
            return
        sp.run(["dvc", "add", "--quiet", path], check=True)


def check_ignore(path: PathLike) -> bool:
    proc: sp.CompletedProcess[bytes] = sp.run(
        ["dvc", "check-ignore", "--quiet", path], check=False
    )
    return proc.returncode == 0


def tracked_by_git(path: PathLike) -> bool:
    path: Path = _path.as_path(path).absolute()
    try:
        repo = git.Repo(search_parent_directories=True)
        repo.git.ls_files(path, error_unmatch=True)
    except git.exc.GitCommandError:
        return False
    return True

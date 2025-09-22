from pathlib import Path

import git.exc

from liblaf import grapes
from liblaf.cherries import pathutils

from ._git import git_info


def project_name() -> str | None:
    try:
        info: grapes.git.GitInfo = git_info()
    except git.exc.InvalidGitRepositoryError:
        return None
    else:
        return info.repo


def exp_name() -> str:
    exp_dir: Path = pathutils.exp_dir(absolute=False)
    exp_name: str = pathutils.as_posix(exp_dir)
    exp_name = exp_name.removeprefix("exp")
    exp_name = exp_name.removeprefix("/")
    return exp_name

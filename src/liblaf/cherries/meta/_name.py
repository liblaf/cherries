from pathlib import Path

import git.exc

from liblaf import grapes
from liblaf.cherries import pathutils as _path

from ._git import git_info


def project_name() -> str:
    try:
        info: grapes.git.GitInfo = git_info()
    except git.exc.InvalidGitRepositoryError:
        return "Default"
    else:
        return info.repo


def exp_name() -> str:
    exp_dir: Path = _path.entrypoint(absolute=False)
    exp_name: str = _path.as_posix(exp_dir)
    exp_name = exp_name.removeprefix("exp")
    exp_name = exp_name.removeprefix("/")
    return exp_name

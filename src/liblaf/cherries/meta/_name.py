from pathlib import Path

import git.exc

from liblaf.cherries import path_utils

from ._git import GitInfo, git_info


def project_name() -> str | None:
    try:
        info: GitInfo = git_info()
    except git.exc.InvalidGitRepositoryError:
        return None
    else:
        return info.repo


def exp_name() -> str:
    exp_dir: Path = path_utils.exp_dir(absolute=False)
    exp_name: str = path_utils.as_posix(exp_dir)
    exp_name = exp_name.removeprefix("exp")
    exp_name = exp_name.removeprefix("/")
    return exp_name

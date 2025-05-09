from pathlib import Path

import git.exc
from environs import env

from liblaf import grapes
from liblaf.cherries import pathutils as _path

from ._git import git_info


def exp_name() -> str:
    if name := env.str("LIBLAF_CHERRIES_EXPERIMENT_NAME", "").strip():
        return name
    if name := env.str("MLFLOW_EXPERIMENT_NAME", "").strip():
        return name
    try:
        info: grapes.git.GitInfo = git_info()
    except git.exc.InvalidGitRepositoryError:
        return "Default"
    else:
        return info.repo


def run_name() -> str:
    run_dir: Path = _path.run_dir(absolute=False)
    run_name: str = _path.as_posix(run_dir)
    run_name = run_name.removeprefix("exp")
    run_name = run_name.removeprefix("/")
    return run_name

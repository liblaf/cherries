import git.exc
from environs import env

from liblaf import grapes

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

import git.exc

from liblaf import grapes

from ._git import git_info


def exp_name() -> str:
    try:
        info: grapes.git.GitInfo = git_info()
    except git.exc.InvalidGitRepositoryError:
        return "Default"
    else:
        return info.repo

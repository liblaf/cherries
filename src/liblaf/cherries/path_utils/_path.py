import sys
from pathlib import Path

import git
import git.exc
from loguru import logger

from liblaf.cherries import utils


@utils.cache
def entrypoint(*, absolute: bool = True) -> Path:
    path = Path(sys.argv[0])
    if absolute:
        return path.absolute()
    return path.relative_to(project_dir())


EXP_DIR_NAMES: set[str] = {"exp", "experiment", "experiments", "exps", "src"}


@utils.cache
def exp_dir(*, absolute: bool = True) -> Path:
    entrypoint_: Path = entrypoint(absolute=True)
    parent: Path = entrypoint_.parent
    exp_dir: Path
    exp_dir = parent.parent if parent.name in EXP_DIR_NAMES else parent
    if absolute:
        return exp_dir
    exp_dir = exp_dir.relative_to(project_dir())
    return exp_dir


@utils.cache
def project_dir() -> Path:
    exp_dir_: Path = exp_dir(absolute=True)
    try:
        repo = git.Repo(exp_dir_, search_parent_directories=True)
    except git.exc.InvalidGitRepositoryError:
        logger.warning("Not in a git repository, using current directory", once=True)
        return exp_dir_
    else:
        return Path(repo.working_dir)

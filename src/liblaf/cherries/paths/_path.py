import sys
from collections.abc import Container
from pathlib import Path

import git
import git.exc
from loguru import logger

from liblaf.cherries import utils


@utils.cache
def entrypoint(*, absolute: bool = True) -> Path:
    if absolute:
        return _entrypoint_absolute()
    return _entrypoint_relative()


@utils.cache
def git_root() -> Path:
    entrypoint: Path = _entrypoint_absolute()
    repo = git.Repo(entrypoint, search_parent_directories=True)
    return Path(repo.working_dir)


@utils.cache
def git_root_safe() -> Path:
    try:
        return git_root()
    except git.exc.InvalidGitRepositoryError:
        logger.warning("Not in a git repository, using current directory", once=True)
        return _entrypoint_absolute().parent


@utils.cache
def exp_dir(*, absolute: bool = True) -> Path:
    if absolute:
        return _exp_dir_absolute()
    return _exp_dir_relative()


@utils.cache
def _entrypoint_absolute() -> Path:
    path = Path(sys.argv[0])
    return path.absolute()


@utils.cache
def _entrypoint_relative() -> Path:
    path: Path = _entrypoint_absolute()
    return path.relative_to(git_root_safe())


EXP_DIR_NAMES: Container[str] = {"exp", "experiment", "experiments", "exps", "src"}


@utils.cache
def _exp_dir_absolute() -> Path:
    entrypoint: Path = _entrypoint_absolute()
    parent: Path = entrypoint.parent
    if parent.name in EXP_DIR_NAMES:
        return parent.parent
    return parent


@utils.cache
def _exp_dir_relative() -> Path:
    absolute: Path = _exp_dir_absolute()
    root: Path = git_root_safe()
    return absolute.relative_to(root)

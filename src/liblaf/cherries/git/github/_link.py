import os
from pathlib import Path

import git

from . import user_repo


def permalink(
    repo: git.Repo | None = None, filepath: str | os.PathLike[str] | None = None
) -> str | None:
    if repo is None:
        repo = git.Repo(search_parent_directories=True)
    user: str | None
    repo_str: str | None
    user, repo_str = user_repo(repo)
    if not (user and repo):
        return None
    sha: str = repo.head.commit.hexsha
    link: str = f"https://github.com/{user}/{repo_str}/tree/{sha}"
    if filepath:
        filepath = Path(filepath).absolute()
        if not filepath.is_relative_to(repo.working_dir):
            return None
        link += f"/{Path(filepath).as_posix()}"

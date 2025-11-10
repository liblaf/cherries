import subprocess as sp
from typing import Protocol

import git
import giturlparse

from liblaf.cherries import path_utils


class GitInfo(Protocol):
    """.

    References:
        1. <https://github.com/nephila/giturlparse/blob/master/README.rst>
    """

    @property
    def host(self) -> str: ...
    @property
    def platform(self) -> str: ...
    @property
    def owner(self) -> str: ...
    @property
    def repo(self) -> str: ...


def git_auto_commit(
    message: str = "chore(cherries): auto commit", *, dry_run: bool = False
) -> None:
    repo: git.Repo = _repo()
    if not repo.is_dirty(untracked_files=True):
        return
    repo.git.add(all=True, dry_run=dry_run)
    sp.run(["git", "status"], check=False)
    if dry_run:
        return
    repo.git.commit(message=message)


def git_branch() -> str:
    repo: git.Repo = _repo()
    return repo.active_branch.name


def git_commit_sha() -> str:
    repo: git.Repo = _repo()
    return repo.head.commit.hexsha


def git_commit_url(sha: str | None = None) -> str:
    if sha is None:
        sha = git_commit_sha()
    info: GitInfo = git_info()
    if info.platform == "github":
        return f"https://github.com/{info.owner}/{info.repo}/commit/{sha}"
    raise NotImplementedError


def git_info() -> GitInfo:
    repo: git.Repo = _repo()
    info: GitInfo = giturlparse.parse(repo.remote().url)  # pyright: ignore[reportAssignmentType]
    return info


def _repo() -> git.Repo:
    return git.Repo(path_utils.exp_dir(absolute=True), search_parent_directories=True)

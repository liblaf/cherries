import subprocess as sp

import git

from liblaf import grapes
from liblaf.cherries import pathutils as _path


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
    info: grapes.git.GitInfo = git_info()
    if info.platform == "github":
        return f"https://github.com/{info.owner}/{info.repo}/commit/{sha}"
    raise NotImplementedError


def git_info() -> grapes.git.GitInfo:
    info: grapes.git.GitInfo = grapes.git.info(
        _path.entrypoint(absolute=True), search_parent_directories=True
    )
    return info


def _repo() -> git.Repo:
    return git.Repo(_path.entrypoint(absolute=True), search_parent_directories=True)

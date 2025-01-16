import subprocess as sp

import git

DEFAULT_COMMIT_MESSAGE: str = """chore(exp): auto commit"""


def commit(message: str = DEFAULT_COMMIT_MESSAGE, *, dry_run: bool = False) -> bool:
    repo = git.Repo(search_parent_directories=True)
    if not repo.is_dirty(untracked_files=True):
        return False
    repo.git.add(all=True, dry_run=dry_run)
    sp.run(["git", "status"], check=False)
    if dry_run:
        return False
    repo.git.commit(message=message)
    return True

from typing import override

import attrs
from environs import env

from liblaf.cherries import info as _info

from ._abc import End, RunStatus, Start
from ._run import run


@attrs.define
class GitEnd(End):
    dry_run: bool = env.bool("LIBLAF_CHERRIES_GIT_DRY_RUN", default=False)

    @override
    def __call__(self, status: RunStatus = RunStatus.FINISHED) -> None:
        git_auto_commit(
            "chore(cherries): auto commit (on run end)", dry_run=self.dry_run
        )


@attrs.define
class GitStart(Start):
    dry_run: bool = env.bool("LIBLAF_CHERRIES_GIT_DRY_RUN", default=False)

    @override
    def __call__(self) -> None:
        git_auto_commit(
            "chore(cherries): auto commit (on run start)", dry_run=self.dry_run
        )


def git_auto_commit(
    header: str = "chore(cherries): auto commit", *, dry_run: bool = False
) -> None:
    body: str = ""
    if run.run_name and run.run_url:
        body += f"🏃 View run {run.run_name} at: {run.run_url}\n"
    if run.exp_name and run.exp_url:
        body += f"🧪 View experiment {run.exp_name} at: {run.exp_url}\n"
    message: str = f"{header}\n\n{body}" if body else header
    _info.git_auto_commit(message, dry_run=dry_run)
    run.set_tag("cherries.git.branch", _info.git_branch())
    run.set_tag("cherries.git.sha", _info.git_commit_sha())
    run.set_tag("cherries.git.url", _info.git_commit_url())

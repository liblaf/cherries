from typing import override

import attrs

from liblaf.cherries import meta as _info

from . import _abc
from ._exp import exp


@attrs.define
class End(_abc.End):
    priority: int = attrs.field(default=-3, kw_only=True)  # before dvc
    dry_run: bool = False

    @override
    def __call__(self, **kwargs) -> None:
        git_auto_commit(
            "chore(cherries): auto commit (on run end)", dry_run=self.dry_run
        )


@attrs.define
class Start(_abc.Start):
    dry_run: bool = False

    @override
    def __call__(self, **kwargs) -> None:
        git_auto_commit(
            "chore(cherries): auto commit (on run start)", dry_run=self.dry_run
        )


def git_auto_commit(
    header: str = "chore(cherries): auto commit", *, dry_run: bool = False
) -> None:
    body: str = ""
    if exp.exp_name and exp.exp_url:
        body += f"🧪 View experiment {exp.exp_name} at: {exp.exp_url}\n"
    message: str = f"{header}\n\n{body}" if body else header
    _info.git_auto_commit(message, dry_run=dry_run)
    exp.log_other("cherries.git.branch", _info.git_branch())
    exp.log_other("cherries.git.sha", _info.git_commit_sha())
    exp.log_other("cherries.git.url", _info.git_commit_url())

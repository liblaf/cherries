import functools
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, override

import attrs
import git
import msgspec

from liblaf.cherries import core

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Git(core.Plugin, core.PluginProtocol):
    run: core.Run
    commit: bool = attrs.field(default=True, kw_only=True)
    verify: bool = attrs.field(default=False, kw_only=True)

    @override
    @core.impl(before=("Comet",))
    def end(self, exc: BaseException | None = None) -> None:
        if self.repo is None:
            return
        if self.commit and self.repo.is_dirty(untracked_files=True):
            message: str = self._make_commit_message()
            try:
                self.repo.git.add(all=True)
                subprocess.run(["git", "status"], check=False)
                self.repo.git.commit(message=message, no_verify=not self.verify)
            except git.GitCommandError:
                logger.exception("")
        self.run.log_other("cherries/git/sha", self.repo.head.commit.hexsha)

    def _make_commit_message(self) -> str:
        assert self.repo is not None
        summary: dict[str, Any] = self.run.summary(prefix=self.repo.working_dir)
        message: str = f"chore(exp): {summary.pop('name')}\n\n"
        message += _pretty_yaml(summary)
        return message

    def _relative_to_repo(self, path: Path) -> Path:
        if self.repo is None:
            return path
        try:
            return path.relative_to(self.repo.working_dir)
        except ValueError:
            return path

    @functools.cached_property
    def repo(self) -> git.Repo | None:
        return self.run.repo


@functools.singledispatch
def _enc_hook(obj: Any) -> Any:
    return obj


@_enc_hook.register(os.PathLike)
def _(obj: os.PathLike) -> str:
    return os.fsdecode(obj)


def _pretty_yaml(data: dict[str, Any]) -> str:
    return msgspec.yaml.encode(data, enc_hook=_enc_hook).decode()

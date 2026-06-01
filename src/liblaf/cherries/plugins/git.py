import functools
import logging
import subprocess
from pathlib import Path
from typing import Any, override

import attrs
import git

from liblaf.cherries import core
from liblaf.cherries.utils import pretty_yaml

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Git(core.Plugin, core.PluginProtocol):
    """Record Git metadata and optionally commit dirty experiment outputs.

    Attributes:
        run: Run that owns this plugin.
        commit: Whether to commit dirty changes during `end()`.
        verify: Whether Git hooks should run for the generated commit.
    """

    run: core.Run
    commit: bool = attrs.field(default=False, kw_only=True)
    verify: bool = attrs.field(default=False, kw_only=True)

    @override
    @core.impl(before=("Comet",))
    def end(self, exc: BaseException | None = None) -> None:
        """Commit dirty changes if configured and log the final Git SHA."""
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
        """Build the generated experiment commit message."""
        assert self.repo is not None
        summary: dict[str, Any] = self.run.summary(prefix=self.repo.working_dir)
        message: str = f"chore(exp): {summary.pop('name')}\n\n"
        message += pretty_yaml(summary)
        return message

    def _relative_to_repo(self, path: Path) -> Path:
        """Return `path` relative to the repository when possible."""
        if self.repo is None:
            return path
        try:
            return path.relative_to(self.repo.working_dir)
        except ValueError:
            return path

    @functools.cached_property
    def repo(self) -> git.Repo | None:
        """Repository associated with the owning run."""
        return self.run.repo

import functools
import logging
import os
import shlex
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, override

import attrs
import git
import msgspec

from liblaf.cherries import core

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Git(core.Plugin, core.PluginProtocol):
    """Write experiment summaries and optionally commit Git changes.

    The summary includes the experiment name, command, working directory,
    parameters, reported input/output/temp files, and the exception type when a
    run fails. When `commit` is true, dirty changes are committed before the
    final Git SHA is logged back to the run.
    """

    commit: bool = False
    """Commit dirty repository changes at run end when true."""

    verify: bool = False
    """Run Git commit hooks when true."""

    _inputs: list[Path] = attrs.field(factory=list)
    _outputs: list[Path] = attrs.field(factory=list)
    _temps: list[Path] = attrs.field(factory=list)

    @override
    @core.impl(before=("Comet",))
    def end(self, *args, exc: BaseException | None = None, **kwargs) -> None:
        """Write the summary, optionally commit, and log the final SHA."""
        summary: dict[str, Any] = self._make_summary(exc=exc)
        self._log_summary(summary)
        if self.repo is None:
            return
        if self.commit and self.repo.is_dirty(untracked_files=True):
            try:
                self.repo.git.add(all=True)
                subprocess.run(["git", "status"], check=False)
                message: str = self._make_commit_message(summary)
                self.repo.git.commit(message=message, no_verify=not self.verify)
            except git.GitCommandError:
                logger.exception("")
        self.manager.log_other("cherries.git.sha", self.repo.head.commit.hexsha)

    @override
    @core.impl
    def log_input(
        self, path: Path, name: Path, *, report: bool = True, **kwargs
    ) -> None:
        """Record an input path for the Git summary."""
        if not report:
            return
        self._inputs.append(self._relative_to_repo(path))

    @override
    @core.impl
    def log_output(
        self, path: Path, name: Path, *, report: bool = True, **kwargs
    ) -> None:
        """Record an output path for the Git summary."""
        if not report:
            return
        self._outputs.append(self._relative_to_repo(path))

    @override
    @core.impl
    def log_temp(
        self, path: Path, name: Path, *, report: bool = True, **kwargs
    ) -> None:
        """Record a temporary path for the Git summary."""
        if not report:
            return
        self._temps.append(self._relative_to_repo(path))

    def _log_summary(self, summary: dict[str, Any]) -> None:
        """Log a YAML experiment summary."""
        logger.info(
            """Cherries Experiment Summary:
---
%s
---""",
            _pretty_yaml(summary),
        )

    def _make_commit_message(self, summary: dict[str, Any]) -> str:
        """Build the commit message used for automatic experiment commits."""
        name: str = summary["name"]
        message: str = f"chore(exp): {name}\n\n"
        message += _pretty_yaml(summary)
        return message

    def _make_summary(self, exc: BaseException | None = None) -> dict[str, Any]:
        """Build a serializable summary of the current run."""
        summary: dict[str, Any] = {"name": self.manager.exp_name}
        if url := self.manager.url:
            summary["url"] = url
        exp_dir: Path = self.manager.exp_dir
        cwd: Path = Path.cwd().resolve()
        if self.repo is not None:
            exp_dir: Path = self._relative_to_repo(exp_dir)
            cwd: Path = self._relative_to_repo(cwd)
        summary["exp_dir"] = exp_dir
        summary["cwd"] = cwd
        summary["cmd"] = shlex.join(sys.orig_argv)
        if params := self.manager.get_params():
            summary["params"] = params
        if exc is not None:
            summary["exception"] = "\n".join(traceback.format_exception_only(exc))
        if inputs := self._inputs:
            summary["inputs"] = inputs
        if outputs := self._outputs:
            summary["outputs"] = outputs
        if temps := self._temps:
            summary["temps"] = temps
        return summary

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
        """Repository reported by the run manager."""
        return self.manager.repo


@functools.singledispatch
def _enc_hook(obj: Any) -> Any:
    """Encode extra Python objects for `msgspec.yaml`."""
    return obj


@_enc_hook.register(os.PathLike)
def _(obj: os.PathLike) -> str:
    """Encode path-like objects as file-system strings."""
    return os.fsdecode(obj)


def _pretty_yaml(data: dict[str, Any]) -> str:
    """Serialize `data` as human-readable YAML."""
    return msgspec.yaml.encode(data, enc_hook=_enc_hook).decode()

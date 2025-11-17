import logging
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, override

import attrs
import git

from liblaf import grapes
from liblaf.cherries import core

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Git(core.PluginSchema):
    commit: bool = False
    inputs: list[Path] = attrs.field(factory=list)
    outputs: list[Path] = attrs.field(factory=list)
    repo: git.Repo = attrs.field(default=None)
    temps: list[Path] = attrs.field(factory=list)
    verify: bool = False

    @override
    @core.impl(before=("Comet",))
    def end(self, *args, **kwargs) -> None:
        if self.commit and self.repo.is_dirty(untracked_files=True):
            try:
                self.repo.git.add(all=True)
                subprocess.run(["git", "status"], check=False)
                message: str = self._make_commit_message()
                self.repo.git.commit(message=message, no_verify=not self.verify)
            except git.GitCommandError:
                logger.exception("")
        self.run.log_other("cherries.git.sha", self.repo.head.commit.hexsha)

    @override
    @core.impl
    def log_input(self, path: Path, name: Path, **kwargs) -> None:
        self.inputs.append(self._relative_to_repo(path))

    @override
    @core.impl
    def log_output(self, path: Path, name: Path, **kwargs) -> None:
        self.outputs.append(self._relative_to_repo(path))

    @override
    @core.impl
    def log_temp(self, path: Path, name: Path, **kwargs) -> None:
        self.temps.append(self._relative_to_repo(path))

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        self.repo = git.Repo(search_parent_directories=True)

    def _make_commit_message(self) -> str:
        name: str = self.run.exp_name
        message: str = f"chore(cherries): {name}\n\n"
        meta: dict[str, Any] = {}
        if url := self.run.url:
            meta["url"] = url
        meta["exp_dir"] = self.run.exp_dir.relative_to(self.repo.working_dir)
        meta["cwd"] = Path.cwd().relative_to(self.repo.working_dir)
        meta["cmd"] = shlex.join(sys.orig_argv)
        if params := self.run.get_params():
            meta["params"] = params
        if inputs := self.inputs:
            meta["inputs"] = inputs
        if outputs := self.outputs:
            meta["outputs"] = outputs
        if temps := self.temps:
            meta["temps"] = temps
        message += grapes.yaml.encode(meta).decode()
        return message

    def _relative_to_repo(self, path: Path) -> Path:
        if self.repo is None:
            return path
        try:
            return path.relative_to(self.repo.working_dir)
        except ValueError:
            return path

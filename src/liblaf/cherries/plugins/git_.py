import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, override

import attrs
import git
from loguru import logger

from liblaf import grapes
from liblaf.cherries import core
from liblaf.cherries.typing import PathLike


@attrs.define
class Git(core.Run):
    commit: bool = True
    inputs: list[Path] = attrs.field(factory=list)
    outputs: list[Path] = attrs.field(factory=list)
    repo: git.Repo = attrs.field(default=None)
    verify: bool = False

    @override
    @core.impl(after=("Dvc",))
    def end(self, *args, **kwargs) -> None:
        if self.commit and self.repo.is_dirty(untracked_files=True):
            try:
                self.repo.git.add(all=True)
                subprocess.run(["git", "status"], check=False)
                message: str = self._make_commit_message()
                self.repo.git.commit(message=message, no_verify=not self.verify)
            except git.GitCommandError as err:
                logger.exception(err)
        self.plugin_root.log_other("cherries.git.sha", self.repo.head.commit.hexsha)

    @override
    @core.impl
    def log_input(self, path: PathLike, *args, **kwargs) -> None:
        path: Path = Path(path)
        self.inputs.append(path.relative_to(self.project_dir))

    @override
    @core.impl
    def log_output(
        self,
        path: PathLike,
        name: PathLike | None = None,
        **kwargs,
    ) -> None:
        path: Path = Path(path)
        self.outputs.append(path.relative_to(self.project_dir))

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        self.repo = git.Repo(search_parent_directories=True)

    def _make_commit_message(self) -> str:
        name: str = self.exp_name
        message: str = f"chore(cherries): {name}\n\n"
        meta: dict[str, Any] = {}
        if url := self.url:
            meta["url"] = url
        meta["exp_dir"] = self.exp_dir.relative_to(self.project_dir)
        meta["cwd"] = Path.cwd().relative_to(self.project_dir)
        meta["cmd"] = shlex.join(sys.orig_argv)
        if params := self.params:
            meta["params"] = params
        if inputs := self.inputs:
            meta["inputs"] = inputs
        if outputs := self.outputs:
            meta["outputs"] = outputs
        message += grapes.yaml.encode(meta).decode()
        return message

import os
import subprocess as sp
from pathlib import Path

import pydantic
import pydantic_settings as ps
from loguru import logger

from liblaf import cherries


def default_config() -> Path:
    git_root: Path = cherries.git.root()
    for path in [
        git_root / ".config" / "resticprofile.toml",
        git_root / "resticprofile.toml",
    ]:
        if path.exists():
            return path
    return git_root / ".config" / "resticprofile.toml"


class PluginRestic(cherries.Plugin):
    model_config = ps.SettingsConfigDict(env_prefix="LIBLAF_CHERRIES_RESTIC_")
    config: Path = pydantic.Field(default_factory=default_config)
    name: str | None = None
    dry_run: bool = False

    def _pre_end(self, run: cherries.Run) -> None:
        if not self.config.exists():
            logger.warning("configuration file '{}' was not found", self.config)
            return
        args: list[str | os.PathLike[str]] = [
            "resticprofile",
            "--config",
            self.config,
            "backup",
        ]
        if self.name:
            args += ["--name", self.name]
        if self.dry_run:
            args.append("--dry-run")
        args += ["--time", run.creation_time.strftime("%Y-%m-%d %H:%M:%S")]
        proc: sp.CompletedProcess[bytes] = sp.run(args, check=False)
        run.log_other("cherries/restic/returncode", proc.returncode)

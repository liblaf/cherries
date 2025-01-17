import contextlib
import json
import os
import subprocess as sp
from pathlib import Path
from typing import Any

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
    model_config = ps.SettingsConfigDict(env_prefix=cherries.ENV_PREFIX + "RESTIC_")
    config: Path = pydantic.Field(default_factory=default_config)
    name: str | None = None
    dry_run: bool = False

    def _pre_end(self, run: cherries.Experiment) -> None:
        if not self.config.exists():
            logger.warning("configuration file '{}' was not found", self.config)
            return
        args: list[str | os.PathLike[str]] = [
            "resticprofile",
            "--config",
            self.config,
            "backup",
            "--json",
        ]
        if self.name:
            args += ["--name", self.name]
        if self.dry_run:
            args.append("--dry-run")
        args += ["--time", run.start_time.strftime("%Y-%m-%d %H:%M:%S")]
        proc: sp.Popen[str] = sp.Popen(
            args, stdout=sp.PIPE, cwd=cherries.git.root(), text=True
        )
        assert proc.stdout is not None
        for line_ in proc.stdout:
            line: str = line_.rstrip()
            logger.debug("{}", line)
            with contextlib.suppress(json.JSONDecodeError):
                log: dict[str, Any] = json.loads(line)
                if log["message_type"] == "summary":
                    run.log_other("cherries/restic", log)
        returncode: int = proc.wait()
        run.log_other("cherries/restic/returncode", returncode)

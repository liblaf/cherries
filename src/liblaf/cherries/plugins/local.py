import functools
import itertools
import logging
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, override

import attrs
from liblaf.logging import FileHandler, LimitsFilter

from liblaf.cherries import core
from liblaf.cherries.utils import relative_or_name

logger: logging.Logger = logging.getLogger(__name__)

_PATH_SKIP_NAMES: set[str] = {"exp", "src"}


@attrs.define
class Local(core.Plugin, core.PluginProtocol):
    """Copy the entrypoint, logs, and artifacts into `.cherries/runs/`.

    Attributes:
        run: Run that owns this plugin.
    """

    run: core.Run

    @functools.cached_property
    def folder(self) -> Path:
        """Snapshot directory for this run."""
        local_dir: Path = self.run.project_dir / ".cherries"
        exp_path: Path = self.run.working_dir.relative_to(self.run.project_dir)
        exp_path: Path = Path(
            *itertools.dropwhile(_PATH_SKIP_NAMES.__contains__, exp_path.parts)
        )
        entrypoint: Path = self.run.entrypoint
        folder: Path = (
            local_dir
            / "runs"
            / exp_path
            / entrypoint.stem
            / self.run.start_time.strftime("%Y-%m-%dT%H%M%S")
        )
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / ".gitignore").write_text("*\n")
        return folder

    @property
    def log_file(self) -> Path:
        """Log file inside the local snapshot."""
        return self.folder / "logs" / self.run.entrypoint.with_suffix(".log").name

    @override
    @core.impl
    def start(self) -> None:
        """Configure local logging and copy the entrypoint."""
        self._config_logging()
        self._copy(self.run.entrypoint, self.folder / "src" / self.run.entrypoint.name)

    @override
    @core.impl
    def log_asset(
        self,
        path: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        report: bool = True,
    ) -> None:
        """Copy `path` under the snapshot's `assets/` directory."""
        if path.is_relative_to(self.run.working_dir):
            target: Path = self.folder / path.relative_to(self.run.working_dir)
        else:
            target: Path = self.folder / "assets" / path.name
        self._copy(path, target)

    def _config_logging(self) -> None:
        """Attach a bounded file handler for the local snapshot log."""
        logger: logging.Logger = logging.getLogger()
        handler: logging.Handler = FileHandler(self.log_file)
        handler.addFilter(LimitsFilter())
        logger.addHandler(handler)

    def _copy(self, source: Path, target: Path) -> None:
        """Copy a file or directory into the snapshot."""
        if target.exists():
            if target.samefile(self.log_file):
                return
            logger.warning("Overwriting existing file: %s", target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)

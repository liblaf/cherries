import functools
import logging
import shutil
from pathlib import Path
from typing import override

import attrs
import liblaf.logging as _log
from liblaf.logging import FileHandler, LimitsFilter

from liblaf.cherries import core

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Local(core.Plugin, core.PluginProtocol):
    """Copy the entrypoint, logs, and assets into a local `.cherries/` folder.

    Snapshots are grouped by entrypoint stem and start timestamp so `debug`
    profile runs leave inspectable local artifacts without remote side effects.
    """

    @functools.cached_property
    def folder(self) -> Path:
        """Timestamped folder for this local run snapshot."""
        local_dir: Path = self.manager.exp_dir / ".cherries"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / ".gitignore").write_text("*\n")
        entrypoint: Path = self.manager.entrypoint
        folder: Path = (
            local_dir
            / entrypoint.stem
            / self.manager.start_time.strftime("%Y-%m-%dT%H%M%S")
        )
        return folder

    @property
    def log_file(self) -> Path:
        """Log file captured inside the local run snapshot."""
        return self.folder / "logs" / self.manager.entrypoint.with_suffix(".log").name

    @override
    @core.impl(before=("Comet",))
    def start(self, *args, **kwargs) -> None:
        """Configure file logging and copy the entrypoint source file."""
        self._config_logging()
        self._copy(
            self.manager.entrypoint, self.folder / "src" / self.manager.entrypoint.name
        )

    @override
    @core.impl
    def log_asset(self, path: Path, name: Path, **kwargs) -> None:
        """Copy a generic artifact into the snapshot."""
        __tracebackhide__ = True
        target: Path = self.folder / name
        self._copy(path, target)

    @override
    @core.impl
    def log_input(self, path: Path, name: Path, **kwargs) -> None:
        """Copy an input artifact under `inputs/`."""
        __tracebackhide__ = True
        target: Path = self.folder / "inputs" / name
        self._copy(path, target)

    @override
    @core.impl
    def log_output(self, path: Path, name: Path, **kwargs) -> None:
        """Copy an output artifact under `outputs/`."""
        __tracebackhide__ = True
        target: Path = self.folder / "outputs" / name
        self._copy(path, target)

    @override
    @core.impl
    def log_temp(self, path: Path, name: Path, **kwargs) -> None:
        """Copy a temporary artifact under `tmp/`."""
        __tracebackhide__ = True
        target: Path = self.folder / "tmp" / name
        self._copy(path, target)

    def _config_logging(self) -> None:
        logger: logging.Logger = logging.getLogger()
        handler: logging.Handler = FileHandler(self.log_file)
        handler.addFilter(LimitsFilter())
        logger.addHandler(handler)

    def _copy(self, source: Path, target: Path) -> None:
        __tracebackhide__ = True
        if target.exists():
            if target.samefile(self.log_file):
                return
            _log.warning("Overwriting existing file: %s", target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)

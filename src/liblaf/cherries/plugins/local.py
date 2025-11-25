import logging
import shutil
from pathlib import Path
from typing import override

import attrs
from liblaf.grapes.logging import RichFileHandler, as_filter, autolog

from liblaf.cherries import core

logger: logging.Logger = logging.getLogger(__name__)


@attrs.define
class Local(core.PluginSchema):
    folder: Path = attrs.field(default=None)

    @property
    def log_file(self) -> Path:
        return self.folder / "logs" / self.run.entrypoint.with_suffix(".log").name

    @override
    @core.impl
    def log_asset(self, path: Path, name: Path, **kwargs) -> None:
        __tracebackhide__ = True
        target: Path = self.folder / name
        self._copy(path, target)

    @override
    @core.impl
    def log_input(self, path: Path, name: Path, **kwargs) -> None:
        __tracebackhide__ = True
        target: Path = self.folder / "inputs" / name
        self._copy(path, target)

    @override
    @core.impl
    def log_output(self, path: Path, name: Path, **kwargs) -> None:
        __tracebackhide__ = True
        target: Path = self.folder / "outputs" / name
        self._copy(path, target)

    @override
    @core.impl
    def log_temp(self, path: Path, name: Path, **kwargs) -> None:
        __tracebackhide__ = True
        target: Path = self.folder / "temp" / name
        self._copy(path, target)

    @override
    @core.impl(after=("Logging",))
    def start(self, *args, **kwargs) -> None:
        local_dir: Path = self.run.exp_dir / ".cherries"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / ".gitignore").write_text("*\n")
        entrypoint: Path = self.run.entrypoint
        self.folder = (
            local_dir
            / entrypoint.stem
            / self.run.start_time.strftime("%Y-%m-%dT%H%M%S")
        )
        self._copy(entrypoint, self.folder / "src" / entrypoint.name)
        self._config_logging()

    def _config_logging(self) -> None:
        logger: logging.Logger = logging.getLogger()
        handler = RichFileHandler(self.log_file)
        handler.addFilter(as_filter())
        logger.addHandler(handler)

    def _copy(self, source: Path, target: Path) -> None:
        __tracebackhide__ = True
        if target.exists():
            if target.samefile(self.log_file):
                return
            autolog.warning("Overwriting existing file: %s", target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)

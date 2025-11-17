import shutil
from pathlib import Path
from typing import override

import attrs

from liblaf.cherries import core


@attrs.define
class Local(core.PluginSchema):
    folder: Path = attrs.field(default=None)

    @override
    @core.impl
    def log_asset(self, path: Path, name: Path, **kwargs) -> None:
        target: Path = self.folder / name
        _copy(path, target)

    @override
    @core.impl
    def log_input(self, path: Path, name: Path, **kwargs) -> None:
        target: Path = self.folder / "inputs" / name
        _copy(path, target)

    @override
    @core.impl
    def log_output(self, path: Path, name: Path, **kwargs) -> None:
        target: Path = self.folder / "outputs" / name
        _copy(path, target)

    @override
    @core.impl
    def log_temp(self, path: Path, name: Path, **kwargs) -> None:
        target: Path = self.folder / "temp" / name
        _copy(path, target)

    @override
    @core.impl
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
        _copy(entrypoint, self.folder / "src" / entrypoint.name)


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)

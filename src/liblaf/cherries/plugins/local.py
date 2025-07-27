import shutil
from pathlib import Path
from typing import override

import attrs

from liblaf.cherries import core
from liblaf.cherries.typed import PathLike


@attrs.define
class Local(core.Run):
    folder: Path = attrs.field(default=None)

    @override
    @core.impl
    def log_asset(
        self,
        path: PathLike,
        name: PathLike | None = None,
        **kwargs,
    ) -> None:
        if name is None:
            name = Path(path).name
        target: Path = self.folder / name
        self._copy(path, target)

    @override
    @core.impl
    def log_input(
        self,
        path: PathLike,
        name: PathLike | None = None,
        **kwargs,
    ) -> None:
        if name is None:
            name = Path(path).name
        name = f"inputs/{name}"
        self.log_asset(path, name, **kwargs)

    @override
    @core.impl
    def log_output(
        self,
        path: PathLike,
        name: PathLike | None = None,
        **kwargs,
    ) -> None:
        if name is None:
            name = Path(path).name
        name = f"outputs/{name}"
        self.log_asset(path, name, **kwargs)

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        self.folder = self.plugin_root.exp_dir / ".cherries" / self.plugin_root.name
        entrypoint: Path = self.plugin_root.entrypoint
        self.log_asset(entrypoint, f"src/{entrypoint.name}")

    def _copy(self, source: PathLike, target: PathLike) -> None:
        source = Path(source)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

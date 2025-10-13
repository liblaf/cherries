import shutil
from pathlib import Path
from typing import override

import attrs

from liblaf.cherries import core
from liblaf.cherries.typing import PathLike


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
        path = Path(path)
        if name is None:
            path_absolute: Path = path.resolve()
            if path_absolute.is_relative_to(self.exp_dir):
                name = path_absolute.relative_to(self.exp_dir)
            else:
                name = path
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
        self.folder = (
            self.exp_dir
            / ".cherries"
            / self.entrypoint.stem
            / self.start_time.strftime("%Y-%m-%dT%H%M%S")
        )
        entrypoint: Path = self.entrypoint
        self.log_asset(entrypoint, f"src/{entrypoint.name}")

    def _copy(self, source: PathLike, target: PathLike) -> None:
        source = Path(source)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

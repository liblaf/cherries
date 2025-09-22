import os
import subprocess
from typing import override

import attrs

from liblaf.cherries import core
from liblaf.cherries.typing import PathLike


@attrs.define
class Dvc(core.Run):
    @override
    @core.impl(before=("Comet",))
    def log_asset(self, path: PathLike, *args, **kwargs) -> None:
        if self.check_ignore(path):
            return
        self._dvc("add", "--quiet", path)

    @override
    @core.impl(before=("Comet",))
    def log_input(self, *args, **kwargs) -> None:
        self.log_asset(*args, **kwargs)

    @override
    @core.impl(before=("Comet",))
    def log_output(self, *args, **kwargs) -> None:
        self.log_asset(*args, **kwargs)

    def _dvc(self, *args: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
        subprocess.run(["dvc", *args], check=True)

    def check_ignore(self, path: PathLike) -> bool:
        process: subprocess.CompletedProcess[bytes] = subprocess.run(
            ["dvc", "check-ignore", "--quiet", path], check=False
        )
        return process.returncode == 0

from pathlib import Path
from typing import override

import attrs

from liblaf import grapes
from liblaf.cherries import core


@attrs.define
class Logging(core.Run):
    @property
    def log_file(self) -> Path:
        return self.plugin_root.exp_dir / "run.log"

    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        grapes.logging.init(enable_link=False, file=self.log_file)

    @override
    @core.impl
    def end(self, *args, **kwargs) -> None:
        self.plugin_root.log_asset(self.log_file)

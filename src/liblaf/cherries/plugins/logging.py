from typing import override

import attrs

from liblaf import grapes
from liblaf.cherries import core


@attrs.define
class Logging(core.Run):
    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        profile = grapes.logging.profiles.ProfileCherries(
            handlers=[
                # Comet and many other experiment tracking platforms do not support links
                grapes.logging.rich_handler(enable_link=False),
                grapes.logging.file_handler(sink=self.plugin_root.exp_dir / "run.log"),
            ]
        )
        grapes.logging.init(profile=profile)

    @override
    @core.impl
    def end(self, *args, **kwargs) -> None:
        self.plugin_root.log_asset(self.plugin_root.exp_dir / "run.log")

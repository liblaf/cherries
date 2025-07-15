from typing import override

from liblaf import grapes
from liblaf.cherries import core


class Logging(core.Run):
    @override
    @core.impl
    def start(self, *args, **kwargs) -> None:
        profile = grapes.logging.profiles.ProfileCherries(
            handlers=[
                grapes.logging.rich_handler(),
                grapes.logging.file_handler(sink=self.plugin_root.exp_dir / "run.log"),
            ]
        )
        grapes.logging.init(profile=profile)

    @override
    @core.impl
    def end(self, *args, **kwargs) -> None:
        if (self.plugin_root.exp_dir / "run.log").exists():
            self.plugin_root.log_asset(self.plugin_root.exp_dir / "run.log")
        if (self.plugin_root.exp_dir / "run.log.jsonl").exists():
            self.plugin_root.log_asset(self.plugin_root.exp_dir / "run.log.jsonl")

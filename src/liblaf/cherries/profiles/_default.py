from typing import override

from liblaf.cherries import core, plugins

from ._playground import ProfilePlayground


class ProfileDefault(ProfilePlayground):
    @override  # impl Profile
    def init(self) -> core.Run:
        run: core.Run = super().init()
        run.register(plugins.Comet())
        return run

from typing import override

from liblaf.cherries import core, plugins

from ._abc import Profile


class ProfileDebug(Profile):
    @override
    def init(self) -> core.Run:
        run: core.Run = core.run
        run.plugins.register(plugins.Comet(run=run, disabled=True))
        run.plugins.register(plugins.Git(run=run, commit=False))
        run.plugins.register(plugins.Local(run=run))
        run.plugins.register(plugins.Logging(run=run))
        return run

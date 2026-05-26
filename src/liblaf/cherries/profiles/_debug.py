from typing import override

from liblaf.cherries import core, plugins

from ._abc import Profile


class ProfileDebug(Profile):
    """Local development profile with Comet disabled and Git commits off."""

    @override  # impl Profile
    def init(self) -> core.Run:
        """Return the process-global run configured for local debugging."""
        run: core.Run = core.run
        run.register(plugins.Comet(disabled=True))
        run.register(plugins.Git(commit=False))
        run.register(plugins.Local())
        run.register(plugins.Logging())
        return run

from typing import override

from liblaf.cherries import core, plugins

from ._abc import Profile


class ProfileDefault(Profile):
    """Default profile for normal experiment runs.

    The profile registers Comet, Git with commits enabled, local artifact
    snapshots, and logging.
    """

    @override  # impl Profile
    def init(self) -> core.Run:
        """Return the process-global run configured for normal execution."""
        run: core.Run = core.run
        run.register(plugins.Comet(disabled=False))
        run.register(plugins.Git(commit=True))
        run.register(plugins.Local())
        run.register(plugins.Logging())
        return run

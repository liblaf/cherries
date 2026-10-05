# Copyright (c) 2026 liblaf
from typing import override

from liblaf.cherries import core, plugins

from ._abc import Profile


class ProfileDebug(Profile):
    """Profile for local/debug runs with remote and commit side effects disabled."""

    @override
    def init(self) -> core.Run:
        """Register local logging on the process-global run."""
        run: core.Run = core.run
        run.plugins.register(plugins.Logging(run=run))
        return run

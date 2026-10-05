# Copyright (c) 2026 liblaf
import os
from typing import override

from liblaf.cherries import core, plugins

from ._abc import Profile


class ProfileDefault(Profile):
    """Profile for local CAS recording, logs, and opt-in Comet observability."""

    @override
    def init(self) -> core.Run:
        """Register the production plugin set on the process-global run."""
        run: core.Run = core.run
        if os.environ.get("CHERRIES_COMET", "0") == "1":
            run.plugins.register(plugins.Comet(run=run))
        run.plugins.register(plugins.Logging(run=run))
        return run

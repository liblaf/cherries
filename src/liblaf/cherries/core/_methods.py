from typing import Any

from ._run import Run

run: Run = Run()
"""Process-global run used by Cherries convenience functions."""


def __getattr__(name: str) -> Any:
    """Forward module-level convenience calls to [`run`][liblaf.cherries.core.run]."""
    return getattr(run, name)

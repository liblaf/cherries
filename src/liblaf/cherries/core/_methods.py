from typing import Any

from ._run import Run

run = Run()
"""Process-global run used by top-level convenience functions."""


def __getattr__(name: str) -> Any:
    """Forward module-level method lookups to [`run`][liblaf.cherries.core.run]."""
    return getattr(run, name)

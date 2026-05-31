from typing import Any

from ._run import Run

run = Run()


def __getattr__(name: str) -> Any:
    return getattr(run, name)

# Copyright (c) 2026 liblaf
from typing import TYPE_CHECKING, Any

from .git import Git
from .local import Local
from .logging import Logging

__all__ = ["Comet", "Git", "Local", "Logging"]

if TYPE_CHECKING:
    from .comet import Comet


def __getattr__(name: str) -> Any:
    if name == "Comet":
        from .comet import Comet

        return Comet
    raise AttributeError(name)

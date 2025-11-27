from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import StrPath


def relative_to_or_name(path: Path, prefix: Path) -> StrPath:
    try:
        return path.relative_to(prefix)
    except ValueError:
        return path.name

import os
from pathlib import Path

type PathLike = str | os.PathLike[str]


def relative_to_or_name(path: Path, prefix: Path) -> PathLike:
    try:
        return path.relative_to(prefix)
    except ValueError:
        return path.name

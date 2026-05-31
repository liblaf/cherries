from pathlib import Path


def relative_or_absolute(path: Path, prefix: Path) -> Path:
    if path.is_relative_to(prefix):
        return path.relative_to(prefix)
    return path.resolve()


def relative_or_name(path: Path, prefix: Path) -> Path:
    if path.is_relative_to(prefix):
        return path.relative_to(prefix)
    return Path(path.name)

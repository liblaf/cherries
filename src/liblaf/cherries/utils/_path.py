from pathlib import Path


def relative_or_absolute(path: Path, prefix: Path) -> Path:
    """Return `path` relative to `prefix`, or as an absolute path.

    Args:
        path: Path to display or serialize.
        prefix: Directory that should be stripped when `path` is inside it.

    Returns:
        `path.relative_to(prefix)` when possible; otherwise `path.resolve()`.

    Examples:
        >>> relative_or_absolute(
        ...     Path("/tmp/cherries/data/out.txt"), Path("/tmp/cherries")
        ... )
        PosixPath('data/out.txt')
        >>> relative_or_absolute(Path("/var/tmp/out.txt"), Path("/tmp/cherries"))
        PosixPath('/var/tmp/out.txt')
    """
    if path.is_relative_to(prefix):
        return path.relative_to(prefix)
    return path.resolve()


def relative_or_name(path: Path, prefix: Path) -> Path:
    """Return `path` relative to `prefix`, or just its file name.

    This keeps copied artifact names short even when a user logs a file outside
    the experiment working directory.

    Args:
        path: Path to display or copy.
        prefix: Directory that should be stripped when `path` is inside it.

    Returns:
        `path.relative_to(prefix)` when possible; otherwise `Path(path.name)`.

    Examples:
        >>> relative_or_name(Path("/tmp/cherries/data/out.txt"), Path("/tmp/cherries"))
        PosixPath('data/out.txt')
        >>> relative_or_name(Path("/var/tmp/out.txt"), Path("/tmp/cherries"))
        PosixPath('out.txt')
    """
    if path.is_relative_to(prefix):
        return path.relative_to(prefix)
    return Path(path.name)

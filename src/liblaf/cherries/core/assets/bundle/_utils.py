from pathlib import Path


def relative_or_absolute(path: Path, prefix: Path) -> Path:
    """Return `path` relative to `prefix`, or an absolute path if unrelated.

    Examples:
        >>> relative_or_absolute(
        ...     Path("/tmp/cherries/data/out.txt"), Path("/tmp/cherries")
        ... )
        PosixPath('data/out.txt')
        >>> relative_or_absolute(Path("/var/tmp/out.txt"), Path("/tmp/cherries"))
        PosixPath('/var/tmp/out.txt')
    """
    try:
        return path.relative_to(prefix)
    except ValueError:
        return path.resolve()


def relative_or_name(path: Path, prefix: Path) -> Path:
    """Return `path` relative to `prefix`, or just the file name if unrelated.

    Examples:
        >>> relative_or_name(Path("/tmp/cherries/data/out.txt"), Path("/tmp/cherries"))
        PosixPath('data/out.txt')
        >>> relative_or_name(Path("/var/tmp/out.txt"), Path("/tmp/cherries"))
        PosixPath('out.txt')
    """
    try:
        return path.relative_to(prefix)
    except ValueError:
        return Path(path.name)

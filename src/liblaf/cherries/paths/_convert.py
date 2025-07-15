from pathlib import Path
from typing import overload

from liblaf.cherries.typed import PathLike


@overload
def as_os_path(path: PathLike) -> str: ...
@overload
def as_os_path(path: None) -> None: ...
def as_os_path(path: PathLike | None) -> str | None:
    if path is None:
        return None
    return str(path)


@overload
def as_path(path: PathLike) -> Path: ...
@overload
def as_path(path: None) -> None: ...
def as_path(path: PathLike | None) -> Path | None:
    if path is None:
        return None
    return Path(path)


@overload
def as_posix(path: PathLike) -> str: ...
@overload
def as_posix(path: None) -> None: ...
def as_posix(path: PathLike | None) -> str | None:
    if path is None:
        return None
    if isinstance(path, str):
        return path
    return Path(path).as_posix()

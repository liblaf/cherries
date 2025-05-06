from pathlib import Path

from liblaf.grapes.typed import PathLike

from ._path import exp_dir


def config(path: PathLike = "") -> Path:
    return _path(path, prefix="config")


def data(path: PathLike = "") -> Path:
    return _path(path, prefix="data")


def path(path: PathLike = "") -> Path:
    return _path(path)


def src(path: PathLike = "") -> Path:
    return _path(path, prefix="src")


def _path(path: PathLike = "", *, prefix: PathLike = "") -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return exp_dir() / prefix / path

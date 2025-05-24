from pathlib import Path

from liblaf.grapes.typed import PathLike

from ._path import exp_dir


def config(
    path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "config"
) -> Path:
    return _path(path, mkdir=mkdir, prefix=prefix)


def data(path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "data") -> Path:
    return _path(path, mkdir=mkdir, prefix=prefix)


def inputs(
    path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "data/inputs"
) -> Path:
    return _path(path, mkdir=mkdir, prefix=prefix)


def outputs(
    path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "data/outputs"
) -> Path:
    return _path(path, mkdir=mkdir, prefix=prefix)


def params(
    path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "params"
) -> Path:
    return _path(path, mkdir=mkdir, prefix=prefix)


def path(path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "") -> Path:
    return _path(path, mkdir=mkdir, prefix=prefix)


def src(path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "src") -> Path:
    return _path(path, mkdir=mkdir, prefix=prefix)


def _path(path: PathLike = "", *, mkdir: bool = True, prefix: PathLike = "") -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = exp_dir(absolute=True) / prefix / path
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path

import abc
import os
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

type PathLike = str | os.PathLike[str]


class BundleItem(NamedTuple):
    path: PathLike
    relative: PathLike
    required: bool


class Bundle(abc.ABC):
    @abc.abstractmethod
    def match(self, path: Path) -> bool: ...

    @abc.abstractmethod
    def ls_files(self, path: Path, prefix: Path) -> Iterable[BundleItem]:
        raise NotImplementedError

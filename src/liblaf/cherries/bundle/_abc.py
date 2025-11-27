from __future__ import annotations

import abc
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from _typeshed import StrPath


class BundleItem(NamedTuple):
    path: StrPath
    relative: StrPath
    required: bool


class Bundle(abc.ABC):
    @abc.abstractmethod
    def match(self, path: Path) -> bool: ...

    @abc.abstractmethod
    def ls_files(self, path: Path, prefix: Path) -> Iterable[BundleItem]:
        raise NotImplementedError

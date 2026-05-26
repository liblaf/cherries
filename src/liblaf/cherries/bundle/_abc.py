from __future__ import annotations

import abc
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from _typeshed import StrPath


class BundleItem(NamedTuple):
    """A related file discovered by a bundle plugin.

    Attributes:
        path: Absolute or input-relative path to log.
        name: Asset name relative to the logging prefix.
        optional: Whether missing files should be ignored silently.
    """

    path: StrPath
    name: StrPath
    optional: bool


class Bundle(abc.ABC):
    """Discover files that should be logged together with a primary artifact."""

    @abc.abstractmethod
    def match(self, path: Path) -> bool:
        """Return whether this bundle handles `path`."""

    @abc.abstractmethod
    def ls_files(self, path: Path, prefix: Path) -> Iterable[BundleItem]:
        """Yield related files for `path`.

        Args:
            path: Primary artifact path that matched the bundle.
            prefix: Directory used to compute relative asset names.
        """
        raise NotImplementedError

from __future__ import annotations

import abc
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from _typeshed import StrPath


class BundleItem(NamedTuple):
    """Related file discovered for a logged artifact.

    Attributes:
        path: Related file path.
        optional: Whether a missing related file should be ignored.
    """

    path: StrPath
    optional: bool


class Bundle(abc.ABC):
    """Base class for artifact companion-file discovery."""

    @abc.abstractmethod
    def match(self, path: Path) -> bool:
        """Return whether this bundle can expand `path`.

        Args:
            path: Primary artifact path.

        Returns:
            `True` when [`ls_files`][liblaf.cherries.core.assets.bundle.Bundle.ls_files]
            can yield companion files for `path`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def ls_files(self, path: Path) -> Iterable[BundleItem]:
        """Yield files that should be logged with `path`.

        Args:
            path: Primary artifact path.

        Returns:
            Iterable of companion files and their optional/missing-file policy.
        """
        raise NotImplementedError

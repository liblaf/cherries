import abc
from collections.abc import Iterable
from pathlib import Path


class AssetResolver:
    @property
    def id(self) -> str:
        return type(self).__name__

    @abc.abstractmethod
    def match(self, path: Path) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def resolve(self, path: Path) -> Iterable[Path]:
        raise NotImplementedError

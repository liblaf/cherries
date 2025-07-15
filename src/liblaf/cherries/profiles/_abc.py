import abc

import autoregistry

from liblaf.cherries import core


class Profile(abc.ABC, autoregistry.Registry, prefix="Profile"):
    @abc.abstractmethod
    def init(self) -> core.Run: ...

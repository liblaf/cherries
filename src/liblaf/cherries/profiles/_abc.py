import abc

import autoregistry

from liblaf.cherries import core


class Profile(abc.ABC, autoregistry.Registry, prefix="Profile"):
    """Base class for named run profiles."""

    @abc.abstractmethod
    def init(self) -> core.Run:
        """Configure and return the process-global run."""
        raise NotImplementedError

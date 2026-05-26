import abc

import autoregistry

from liblaf.cherries import core


class Profile(abc.ABC, autoregistry.Registry, prefix="Profile"):
    """Factory for a configured [`Run`][liblaf.cherries.core.Run]."""

    @abc.abstractmethod
    def init(self) -> core.Run:
        """Create or configure a run for this profile."""

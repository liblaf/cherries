from typing import Protocol

from .assets import AssetPluginProtocol
from .metrics import MetricPluginProtocol
from .others import OtherPluginProtocol
from .params import ParamPluginProtocol


class PluginProtocol(
    AssetPluginProtocol,
    MetricPluginProtocol,
    OtherPluginProtocol,
    ParamPluginProtocol,
    Protocol,
):
    """Complete hook surface implemented by Cherries plugin delegates."""

    def start(self) -> None:
        """Start a run."""
        raise NotImplementedError

    def end(self, exc: BaseException | None = None) -> None:
        """End a run.

        Args:
            exc: Exception raised by the experiment, if any.
        """
        raise NotImplementedError

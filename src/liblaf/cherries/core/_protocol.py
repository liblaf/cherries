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
    def start(self) -> None:
        raise NotImplementedError

    def end(self, exc: BaseException | None = None) -> None:
        raise NotImplementedError

from collections.abc import Mapping
from typing import Any

import attrs

from liblaf.cherries.utils import flatten_dict, unflatten_dict

from ._protocol import OtherPluginProtocol


@attrs.define
class OthersManager:
    plugins: OtherPluginProtocol
    others: dict[str, Any] = attrs.field(factory=dict)

    def get_other(self, name: str) -> Any:
        return self.others[name]

    def get_others(self) -> dict[str, Any]:
        return unflatten_dict(self.others)

    def log_other(self, name: str, value: Any) -> None:
        self.others[name] = value
        self.plugins.log_other(name, value)

    def log_others(self, others: Mapping[str, Any]) -> None:
        others: dict[str, Any] = flatten_dict(others)
        self.others.update(others)
        self.plugins.log_others(others)

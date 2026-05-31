from collections.abc import Mapping
from typing import Any

import attrs

from liblaf.cherries.utils import flatten_dict, unflatten_dict

from ._protocol import ParamPluginProtocol


@attrs.define
class ParamsManager:
    plugins: ParamPluginProtocol
    params: dict[str, Any] = attrs.field(factory=dict)

    def get_param(self, name: str) -> Any:
        return self.params[name]

    def get_params(self) -> dict[str, Any]:
        return unflatten_dict(self.params)

    def log_param(self, name: str, value: Any) -> None:
        self.params[name] = value
        self.plugins.log_param(name, value)

    def log_params(self, params: Mapping[str, Any]) -> None:
        params: dict[str, Any] = flatten_dict(params)
        self.params.update(params)
        self.plugins.log_params(params)

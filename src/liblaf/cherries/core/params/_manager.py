from collections.abc import Mapping
from typing import Any

import attrs


@attrs.define
class ParamsManager:
    params: dict[str, Any] = attrs.field(factory=dict, kw_only=True)

    def log_param(self, name: str, value: Any) -> None:
        self.params[name] = value

    def log_params(self, params: dict[str, Any]) -> None:
        for name, value in params.items():
            if isinstance(value, Mapping) and isinstance(
                self.params.get(name), Mapping
            ):
                self.params[name].update(value)
            else:
                self.params[name] = value

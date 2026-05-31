from collections.abc import Mapping
from typing import Any

import attrs

from liblaf.cherries.utils import flatten_dict, unflatten_dict

from ._protocol import ParamPluginProtocol


@attrs.define
class ParamsManager:
    """Store experiment parameters and mirror them to plugins."""

    plugins: ParamPluginProtocol
    """Plugin delegate that receives parameter events."""

    params: dict[str, Any] = attrs.field(factory=dict)
    """Flattened parameter values by slash-delimited name."""

    def get_param(self, name: str) -> Any:
        """Return one flattened parameter value."""
        return self.params[name]

    def get_params(self) -> dict[str, Any]:
        """Return parameters as a nested dictionary."""
        return unflatten_dict(self.params)

    def log_param(self, name: str, value: Any) -> None:
        """Store and publish one parameter."""
        self.params[name] = value
        self.plugins.log_param(name, value)

    def log_params(self, params: Mapping[str, Any]) -> None:
        """Store and publish multiple parameters.

        Nested mappings are flattened before storage and plugin delegation.
        """
        params: dict[str, Any] = flatten_dict(params)
        self.params.update(params)
        self.plugins.log_params(params)

from collections.abc import Mapping
from typing import Any

import attrs

from liblaf.cherries.utils import flatten_dict, unflatten_dict

from ._protocol import OtherPluginProtocol


@attrs.define
class OthersManager:
    """Store miscellaneous run metadata and mirror it to plugins.

    Metadata is stored internally with slash-delimited keys and returned as a
    nested dictionary for summaries.
    """

    plugins: OtherPluginProtocol
    """Plugin delegate that receives metadata events."""

    others: dict[str, Any] = attrs.field(factory=dict)
    """Flattened metadata values by slash-delimited name."""

    def get_other(self, name: str) -> Any:
        """Return one flattened metadata value."""
        return self.others[name]

    def get_others(self) -> dict[str, Any]:
        """Return metadata as a nested dictionary."""
        return unflatten_dict(self.others)

    def log_other(self, name: str, value: Any) -> None:
        """Store and publish one metadata value."""
        self.others[name] = value
        self.plugins.log_other(name, value)

    def log_others(self, others: Mapping[str, Any]) -> None:
        """Store and publish multiple metadata values.

        Nested mappings are flattened before storage and plugin delegation.
        """
        others: dict[str, Any] = flatten_dict(others)
        self.others.update(others)
        self.plugins.log_others(others)

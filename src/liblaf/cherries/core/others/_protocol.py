from typing import Any, Protocol


class OtherPluginProtocol(Protocol):
    """Hook surface for plugins that receive miscellaneous run metadata."""

    def log_other(self, name: str, value: Any) -> None:
        """Record one flattened metadata value."""
        ...

    def log_others(self, others: dict[str, Any]) -> None:
        """Record multiple already-flattened metadata values."""
        ...

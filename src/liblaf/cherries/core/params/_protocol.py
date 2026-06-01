from typing import Any, Protocol


class ParamPluginProtocol(Protocol):
    """Hook surface for plugins that receive experiment parameters."""

    def log_param(self, name: str, value: Any) -> None:
        """Record one flattened parameter value."""
        ...

    def log_params(self, params: dict[str, Any]) -> None:
        """Record multiple already-flattened parameter values."""
        ...

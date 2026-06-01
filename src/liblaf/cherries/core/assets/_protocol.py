from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


class AssetPluginProtocol(Protocol):
    """Hook surface for plugins that receive artifact paths."""

    def log_asset(
        self,
        path: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        report: bool = True,
    ) -> None:
        """Record an existing artifact path.

        Args:
            path: Existing file or directory to record.
            metadata: Optional artifact metadata, usually including `type`.
            report: Whether the path is the primary user-facing artifact.
                Companion files are logged with `report=False`.
        """
        ...

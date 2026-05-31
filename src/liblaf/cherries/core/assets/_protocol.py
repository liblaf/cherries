from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


class AssetPluginProtocol(Protocol):
    def log_asset(
        self,
        path: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        report: bool = True,
    ) -> None: ...

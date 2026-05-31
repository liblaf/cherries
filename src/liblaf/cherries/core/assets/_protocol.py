from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


class AssetPluginProtocol(Protocol):
    @property
    def data_dir(self) -> Path: ...

    @property
    def temp_dir(self) -> Path: ...

    def log_asset(
        self,
        path: Path,
        *,
        metadata: Mapping[str, Any] | None = None,
        report: bool = True,
    ) -> None: ...

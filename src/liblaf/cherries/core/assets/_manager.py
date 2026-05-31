from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import attrs

from ._protocol import AssetPluginProtocol
from .bundle import BundleRegistry, bundles

if TYPE_CHECKING:
    from _typeshed import StrPath


logger: logging.Logger = logging.getLogger(__name__)


@attrs.frozen
class PendingAsset:
    path: Path
    metadata: Mapping[str, Any] | None = None


@attrs.define
class AssetsManager:
    plugins: AssetPluginProtocol
    bundles: BundleRegistry = attrs.field(default=bundles)
    pending: list[PendingAsset] = attrs.field(factory=list)

    @property
    def data_dir(self) -> Path:
        return self.plugins.data_dir

    @property
    def temp_dir(self) -> Path:
        return self.plugins.temp_dir

    def end(self) -> None:
        for asset in self.pending:
            self.log_asset(asset.path, metadata=asset.metadata)

    def input(
        self, name: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> Path:
        path: Path = self.data_dir / name
        metadata: dict[str, Any] = _metadata_with_type(metadata, "input")
        self.log_input(path, metadata=metadata)
        return path

    def output(
        self,
        name: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        path: Path = self.data_dir / name
        if mkdir:
            path.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = _metadata_with_type(metadata, "output")
        self.pending.append(PendingAsset(path=path, metadata=metadata))
        return path

    def temp(
        self,
        name: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        path: Path = self.temp_dir / name
        if mkdir:
            path.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = _metadata_with_type(metadata, "temp")
        self.pending.append(PendingAsset(path=path, metadata=metadata))
        return path

    def log_asset(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> None:
        path: Path = Path(path)
        if not path.exists():
            logger.warning("No such file or directory: %s", path)
            return
        self.plugins.log_asset(path, metadata=metadata, report=True)
        for path_, optional in self.bundles.ls_files(path):
            path: Path = Path(path_)
            if not path.exists():
                if not optional:
                    logger.warning("No such file or directory: %s", path)
                continue
            self.plugins.log_asset(path, metadata=metadata, report=False)

    def log_input(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> None:
        metadata: dict[str, Any] = _metadata_with_type(metadata, "input")
        self.log_asset(path, metadata=metadata)

    def log_output(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> None:
        metadata: dict[str, Any] = _metadata_with_type(metadata, "output")
        self.log_asset(path, metadata=metadata)

    def log_temp(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> None:
        metadata: dict[str, Any] = _metadata_with_type(metadata, "temp")
        self.log_asset(path, metadata=metadata)


def _metadata_with_type(
    metadata: Mapping[str, Any] | None, type_: str
) -> dict[str, Any]:
    meta: dict[str, Any] = {"type": type_}
    if metadata is not None:
        meta.update(metadata)
    return meta

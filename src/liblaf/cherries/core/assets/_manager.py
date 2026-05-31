from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import attrs
import pydantic

from liblaf.cherries.utils import relative_or_absolute

from ._protocol import AssetPluginProtocol
from .bundle import BundleRegistry, bundles

if TYPE_CHECKING:
    from _typeshed import StrPath


logger: logging.Logger = logging.getLogger(__name__)


@attrs.frozen
class PendingAsset:
    """Artifact that should be flushed when a run ends."""

    path: Path
    """Path to log at shutdown."""

    metadata: Mapping[str, Any] | None = None
    """Metadata passed to asset plugins."""


class AssetsSummary(pydantic.BaseModel):
    """Paths successfully reported during a run."""

    assets: list[Path] = pydantic.Field(default_factory=list)
    """Generic asset paths."""

    inputs: list[Path] = pydantic.Field(default_factory=list)
    """Input paths."""

    outputs: list[Path] = pydantic.Field(default_factory=list)
    """Output paths."""

    temps: list[Path] = pydantic.Field(default_factory=list)
    """Temporary artifact paths."""

    def to_dict(self, prefix: StrPath | None = None) -> dict[str, Any]:
        """Serialize non-empty path groups.

        Args:
            prefix: Optional directory to strip from paths before dumping.

        Returns:
            JSON-compatible dictionary with empty/default groups omitted.
        """
        if prefix is not None:
            prefix: Path = Path(prefix)
            obj: AssetsSummary = AssetsSummary(
                assets=[relative_or_absolute(path, prefix) for path in self.assets],
                inputs=[relative_or_absolute(path, prefix) for path in self.inputs],
                outputs=[relative_or_absolute(path, prefix) for path in self.outputs],
                temps=[relative_or_absolute(path, prefix) for path in self.temps],
            )
        else:
            obj: AssetsSummary = self
        return obj.model_dump(mode="json", exclude_defaults=True)


@attrs.define
class AssetsManager:
    """Resolve experiment paths and flush existing artifacts to plugins."""

    working_dir: Path
    """Directory used as the base for `data/` and `tmp/` paths."""

    plugins: AssetPluginProtocol
    """Plugin delegate that receives existing artifacts."""

    bundles: BundleRegistry = attrs.field(default=bundles)
    """Bundle registry used to expand related files."""

    pending: list[PendingAsset] = attrs.field(factory=list)
    """Output and temporary paths waiting for run shutdown."""

    summary: AssetsSummary = attrs.field(factory=AssetsSummary)
    """Artifact summary populated by successful log calls."""

    @property
    def data_dir(self) -> Path:
        """Directory containing input and output data files."""
        return self.working_dir / "data"

    @property
    def temp_dir(self) -> Path:
        """Directory containing temporary artifacts."""
        return self.working_dir / "tmp"

    def end(self) -> None:
        """Flush queued output and temporary paths."""
        for asset in self.pending:
            self.log_asset(asset.path, metadata=asset.metadata)

    def input(
        self, name: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> Path:
        """Resolve and immediately log an input path.

        Args:
            name: Path below `data/`.
            metadata: Extra metadata merged with `{"type": "input"}`.

        Returns:
            Resolved input path.
        """
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
        """Resolve an output path and queue it for end-of-run logging.

        Args:
            name: Path below `data/`.
            metadata: Extra metadata merged with `{"type": "output"}`.
            mkdir: Whether to create the parent directory before returning.

        Returns:
            Resolved output path.
        """
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
        """Resolve a temporary path and queue it for end-of-run logging.

        Args:
            name: Path below `tmp/`.
            metadata: Extra metadata merged with `{"type": "temp"}`.
            mkdir: Whether to create the parent directory before returning.

        Returns:
            Resolved temporary path.
        """
        path: Path = self.temp_dir / name
        if mkdir:
            path.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = _metadata_with_type(metadata, "temp")
        self.pending.append(PendingAsset(path=path, metadata=metadata))
        return path

    def log_asset(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> None:
        """Log an existing path and any companion files from matching bundles.

        Missing primary paths are reported as warnings. Missing optional bundle
        files are ignored, while missing required bundle files are warned.
        """
        path: Path = Path(path)
        if not path.exists():
            logger.warning("No such file or directory: %s", path)
            return
        if metadata is None:
            self.summary.assets.append(path)
        else:
            match metadata.get("type"):
                case "input":
                    self.summary.inputs.append(path)
                case "output":
                    self.summary.outputs.append(path)
                case "temp":
                    self.summary.temps.append(path)
                case _:
                    self.summary.assets.append(path)
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
        """Log `path` as an input artifact."""
        metadata: dict[str, Any] = _metadata_with_type(metadata, "input")
        self.log_asset(path, metadata=metadata)

    def log_output(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> None:
        """Log `path` as an output artifact."""
        metadata: dict[str, Any] = _metadata_with_type(metadata, "output")
        self.log_asset(path, metadata=metadata)

    def log_temp(
        self, path: StrPath, *, metadata: Mapping[str, Any] | None = None
    ) -> None:
        """Log `path` as a temporary artifact."""
        metadata: dict[str, Any] = _metadata_with_type(metadata, "temp")
        self.log_asset(path, metadata=metadata)


def _metadata_with_type(
    metadata: Mapping[str, Any] | None, type_: str
) -> dict[str, Any]:
    meta: dict[str, Any] = {"type": type_}
    if metadata is not None:
        meta.update(metadata)
    return meta

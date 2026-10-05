# Copyright (c) 2026 liblaf
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import attrs
import pydantic

from liblaf.cherries.records import NotFoundError, Store, canonical_json, hash_file
from liblaf.cherries.utils import relative_or_absolute

from ._protocol import AssetPluginProtocol
from .bundle import BundleRegistry, bundles

if TYPE_CHECKING:
    from _typeshed import StrPath


logger: logging.Logger = logging.getLogger(__name__)


@attrs.frozen
class PendingAsset:
    """Artifact that should be flushed when a run ends.

    `output()` and `temp()` return paths before the user has written them. The
    manager stores those paths as pending assets and reports only the ones that
    exist when [`end`][liblaf.cherries.core.assets.AssetsManager.end] runs.
    """

    path: Path
    """Path to log at shutdown."""

    metadata: Mapping[str, Any] | None = None
    """Metadata passed to asset plugins."""


class AssetsSummary(pydantic.BaseModel):
    """Paths successfully reported during a run.

    The summary contains only primary artifacts. Bundle companions are sent to
    plugins, but omitted from this user-facing record.
    """

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

        Examples:
            >>> summary = AssetsSummary(outputs=[Path("/tmp/cherries/data/out.txt")])
            >>> summary.to_dict(prefix="/tmp/cherries")
            {'outputs': ['data/out.txt']}
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
    """Stage independent inputs and declared outputs inside an active run."""

    working_dir: Path
    plugins: AssetPluginProtocol
    bundles: BundleRegistry = attrs.field(default=bundles)
    summary: AssetsSummary = attrs.field(factory=AssetsSummary)
    pending: list[PendingAsset] = attrs.field(factory=list)
    active: bool = False
    store: Store | None = None
    run_id: str | None = None
    bindings: list[dict[str, Any]] = attrs.field(factory=list)
    retained_bundles: list[dict[str, Any]] = attrs.field(factory=list)

    @property
    def data_dir(self) -> Path:
        return self.working_dir / "outputs"

    @property
    def temp_dir(self) -> Path:
        return self.working_dir / "scratch"

    def _check(self) -> None:
        if not self.active:
            msg = (
                "Cherries asset helpers require an active run; call them inside main()."
            )
            raise RuntimeError(msg)

    def _target(self, area: str, name: StrPath) -> Path:
        self._check()
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            msg = "asset names must be contained relative paths"
            raise ValueError(msg)
        target = self.working_dir / area / relative
        if not target.resolve().is_relative_to((self.working_dir / area).resolve()):
            msg = "asset path escapes its run folder"
            raise ValueError(msg)
        return target

    def input(
        self,
        path: StrPath,
        *,
        name: StrPath | None = None,
        source_run: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        self._check()
        original = os.fspath(path)
        declaration = original
        replay = os.environ.get("CHERRIES_REPLAY_INPUTS")
        if replay:
            declaration = json.loads(Path(replay).read_text()).get(
                original, declaration
            )
        binding: dict[str, Any]
        if declaration.startswith(("sha256:", "sha256-tree:", "run:")):
            target, binding = self._reference_input(declaration, name, source_run)
        else:
            source = Path(declaration).expanduser().resolve(strict=True)
            target = self._target("inputs", name or source.name)
            _copy_verified(source, target)
            binding = {
                "asset_id": "sha256:" + hash_file(target) if target.is_file() else None
            }
            if source.is_file():
                self._companions(source, target)
        binding.update(
            {
                "source": original,
                "resolved_source": declaration,
                "staged_path": target.relative_to(self.working_dir).as_posix(),
            }
        )
        binding["input_snapshot"] = self._input_snapshot(target)
        binding["directory"] = target.is_dir()
        self.bindings.append(binding)
        self.summary.inputs.append(target)
        self.plugins.log_asset(
            target, metadata=_metadata_with_type(metadata, "input"), report=True
        )
        return target

    def _input_snapshot(self, primary: Path) -> list[dict[str, str]]:
        files = (
            sorted(path for path in primary.rglob("*") if path.is_file())
            if primary.is_dir()
            else [primary]
        )
        if primary.is_file():
            files.extend(
                Path(path)
                for path, optional in self.bundles.ls_files(primary)
                if Path(path).is_file() or not optional
            )
        return [
            {
                "path": path.relative_to(self.working_dir).as_posix(),
                "asset_id": "sha256:" + hash_file(path),
            }
            for path in files
        ]

    def _validate_inputs(self) -> None:
        for binding in self.bindings:
            primary = self.working_dir / binding["staged_path"]
            if self._input_snapshot(primary) != binding["input_snapshot"]:
                msg = f"staged input was modified during execution: {binding['staged_path']}"
                raise RuntimeError(msg)

    def _reference_input(
        self, declaration: str, name: StrPath | None, source_run: str | None
    ) -> tuple[Path, dict[str, Any]]:
        if self.store is None or self.run_id is None:
            msg = "asset references require a record store"
            raise RuntimeError(msg)
        from liblaf.cherries._settings import configured_remote

        remote = configured_remote(Path.cwd())
        producer, relative, selected, binding = self._resolve_reference(
            declaration, source_run, remote
        )
        receipt = self.store.read_record(producer)
        binding.update(
            {
                "record_digest": hashlib.sha256(canonical_json(receipt)).hexdigest(),
                "manifest_digest": receipt["manifest_digest"],
            }
        )
        if selected:
            binding["members"] = [
                {key: entry[key] for key in ("path", "asset_id", "size")}
                for entry in selected
            ]
        self.store.register_parent(self.run_id, producer)
        reason = "staging:" + self.run_id + ":" + str(uuid.uuid4())
        self.store.hold(producer, reason)
        try:
            target = self._target("inputs", name or Path(relative).name)
            if target.exists():
                raise FileExistsError(target)
            if declaration.startswith("sha256-tree:"):
                self._copy_tree(declaration, target, remote)
            elif selected and not (
                len(selected) == 1 and selected[0]["path"] == relative
            ):
                for entry in selected:
                    source = self._source_path(producer, entry["path"], remote)
                    _copy_verified(
                        source, target / Path(entry["path"]).relative_to(relative)
                    )
            else:
                self._copy_record_file(producer, relative, target, remote, binding)
            return target, binding
        finally:
            self.store.release_hold(producer, reason)

    def _resolve_reference(
        self, declaration: str, source_run: str | None, remote: Any
    ) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
        assert self.store is not None
        if not declaration.startswith("run:"):
            try:
                binding = self.store.resolve_asset(declaration, source_run=source_run)
            except NotFoundError:
                if remote is None:
                    raise
                remote.import_metadata(self.store)
                binding = self._remote_origin(declaration, source_run)
            producer = binding.get("run_id")
            if not producer:
                msg = "asset has no registered producing run"
                raise RuntimeError(msg)
            return producer, binding.get("path", "bundle"), [], binding
        producer, separator, relative = declaration[4:].partition("/")
        if not separator:
            msg = "run references need a logical asset path"
            raise ValueError(msg)
        try:
            producer = self.store.resolve_id(producer)
        except NotFoundError:
            if remote is None:
                raise
            remote.import_metadata(self.store)
            producer = self.store.resolve_id(producer)
        files = self.store.read_manifest(producer)["files"]
        selected = [
            entry
            for entry in files
            if entry["path"] == relative
            or entry["path"].startswith(relative.rstrip("/") + "/")
        ]
        if not selected:
            raise FileNotFoundError(declaration)
        return producer, relative, selected, {"run_id": producer, "path": relative}

    def _remote_origin(
        self, declaration: str, source_run: str | None
    ) -> dict[str, Any]:
        assert self.store is not None
        if not declaration.startswith("sha256-tree:"):
            return self.store.resolve_asset(declaration, source_run=source_run)
        records = (
            [self.store.resolve_id(source_run)]
            if source_run
            else self.store.list_live_records()
        )
        for producer in records:
            record = self.store.read_record(producer)["record"]
            for item in [*record.get("bundles", []), *record.get("input_bindings", [])]:
                if item.get("asset_id") == declaration:
                    return {
                        **item,
                        "run_id": producer,
                        "path": item.get("path", item.get("staged_path", "bundle")),
                    }
        msg = f"asset is not bound to a saved record: {declaration}"
        raise NotFoundError(msg)

    def _copy_tree(self, declaration: str, target: Path, remote: Any) -> None:
        assert self.store is not None
        try:
            self.store.materialize_tree(declaration, target)
        except (NotFoundError, FileNotFoundError):
            if remote is None:
                raise
            remote.fetch_tree(self.store, declaration, target)

    def _copy_record_file(
        self,
        producer: str,
        relative: str,
        target: Path,
        remote: Any,
        binding: dict[str, Any],
    ) -> None:
        assert self.store is not None
        source = self._source_path(producer, relative, remote)
        _copy_verified(source, target)
        binding["asset_id"] = "sha256:" + hash_file(target)
        for companion_name, optional in self.bundles.ls_files(source):
            companion = Path(companion_name)
            if not companion.resolve().is_relative_to(source.parent.resolve()):
                msg = "asset companion escapes its bundle"
                raise ValueError(msg)
            companion_relative = companion.relative_to(
                self.store.root / "runs" / producer
            ).as_posix()
            try:
                child = self._source_path(producer, companion_relative, remote)
            except (NotFoundError, FileNotFoundError):
                if optional:
                    continue
                raise
            _copy_verified(child, target.parent / companion.relative_to(source.parent))
            binding.setdefault("companions", []).append(
                {"path": companion_relative, "asset_id": "sha256:" + hash_file(child)}
            )

    def _source_path(self, producer: str, relative: str, remote: Any) -> Path:
        assert self.store is not None
        try:
            return self.store.materialize(producer, relative)
        except (NotFoundError, FileNotFoundError):
            if remote is None:
                raise
            return remote.fetch_asset(self.store, producer, relative)

    def output(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        target = self._target("outputs", path)
        if mkdir:
            target.parent.mkdir(parents=True, exist_ok=True)
        if any(item.path == target for item in self.pending):
            msg = f"output already declared: {path}"
            raise ValueError(msg)
        self.pending.append(
            PendingAsset(target, _metadata_with_type(metadata, "output"))
        )
        return target

    def temp(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        mkdir: bool = True,
    ) -> Path:
        # Scratch metadata is accepted for old scripts but is not retained.
        del metadata
        target = self._target("scratch", path)
        if mkdir:
            target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _companions(self, source: Path, target: Path) -> None:
        for companion_name, optional in self.bundles.ls_files(source):
            companion = Path(companion_name)
            if not companion.exists():
                if optional:
                    continue
                msg = f"Required asset companion: {companion}"
                raise FileNotFoundError(msg)
            if not companion.resolve().is_relative_to(source.parent.resolve()):
                msg = "asset companion escapes its bundle"
                raise ValueError(msg)
            destination = target.parent / companion.relative_to(source.parent)
            if (
                destination.resolve() != companion.resolve()
                and not destination.exists()
            ):
                _copy_verified(companion, destination)
            self.plugins.log_asset(destination, metadata=None, report=False)

    def _log(
        self,
        path: StrPath,
        area: str,
        kind: str,
        metadata: Mapping[str, Any] | None,
        name: StrPath | None = None,
    ) -> Path:
        self._check()
        source = Path(path).expanduser().resolve(strict=True)
        if source.is_relative_to(self.working_dir / area):
            target = source
        else:
            target = self._target(area, name or source.name)
            _copy_verified(source, target)
        if source.is_file():
            self._companions(source, target)
        getattr(
            self.summary,
            {
                "asset": "assets",
                "input": "inputs",
                "output": "outputs",
                "temp": "temps",
            }[kind],
        ).append(target)
        self.plugins.log_asset(
            target, metadata=_metadata_with_type(metadata, kind), report=True
        )
        return target

    def log_asset(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        name: StrPath | None = None,
    ) -> Path:
        return self._log(path, "artifacts", "asset", metadata, name)

    def log_input(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        name: StrPath | None = None,
    ) -> Path:
        return self.input(path, name=name, metadata=metadata)

    def log_output(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        name: StrPath | None = None,
    ) -> Path:
        return self._log(path, "outputs", "output", metadata, name)

    def log_temp(
        self,
        path: StrPath,
        *,
        metadata: Mapping[str, Any] | None = None,
        name: StrPath | None = None,
    ) -> Path:
        return self._log(path, "artifacts", "temp", metadata, name)

    def end(self) -> None:
        self._check()
        self._validate_inputs()
        for pending in self.pending:
            if not pending.path.exists():
                msg = f"Required output was not written: {pending.path}"
                raise FileNotFoundError(msg)
            self.log_output(pending.path, metadata=pending.metadata)
        self.pending.clear()
        self._retain_bundles()

    def _retain_bundles(self) -> None:
        if self.store is not None:
            primary_paths = sorted(
                set(
                    self.summary.inputs
                    + self.summary.outputs
                    + self.summary.assets
                    + self.summary.temps
                )
            )
            for primary in primary_paths:
                path = primary.relative_to(self.working_dir).as_posix()
                if primary.is_dir():
                    asset_id = self.store.put_tree(primary)
                    self.retained_bundles.append(
                        {"path": path, "asset_id": asset_id, "kind": "directory"}
                    )
                    for binding in self.bindings:
                        if binding["staged_path"] == path:
                            binding["asset_id"] = asset_id
                    continue
                companions = [
                    Path(item)
                    for item, optional in self.bundles.ls_files(primary)
                    if Path(item).exists() or not optional
                ]
                if not companions:
                    continue
                bundle = self.working_dir / "scratch" / "bundles" / str(uuid.uuid4())
                for item in [primary, *companions]:
                    if not item.resolve().is_relative_to(primary.parent.resolve()):
                        msg = "bundle member escapes its primary folder"
                        raise ValueError(msg)
                    _copy_verified(item, bundle / item.relative_to(primary.parent))
                asset_id = self.store.put_tree(bundle)
                self.retained_bundles.append(
                    {
                        "path": path,
                        "asset_id": asset_id,
                        "kind": "companions",
                        "primary": primary.name,
                    }
                )


def _copy_verified(source: Path, target: Path) -> None:
    if target.exists():
        msg = f"asset destination already exists: {target}"
        raise FileExistsError(msg)
    if source.is_dir():
        target.mkdir(parents=True)
        for child in sorted(source.iterdir()):
            if child.is_symlink() and not child.resolve().is_relative_to(
                source.resolve()
            ):
                msg = f"escaping asset symlink: {child}"
                raise ValueError(msg)
            if child.is_symlink() and child.resolve().is_dir():
                msg = f"directory symlink needs an explicit bundle: {child}"
                raise ValueError(msg)
            _copy_verified(child.resolve(), target / child.name)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    before = source.stat()
    if before.st_size < 1024:
        value = source.read_bytes()
        if (
            value.startswith(b"version https://git-lfs.github.com/spec/v1\n")
            and b"\noid sha256:" in value
            and b"\nsize " in value
        ):
            msg = f"input is an unhydrated Git LFS pointer: {source}; run git lfs checkout first"
            raise ValueError(msg)
    source_digest = hash_file(source)
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        try:
            fcntl.ioctl(outgoing.fileno(), 0x40049409, incoming.fileno())
        except OSError:
            shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    shutil.copystat(source, target)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or hash_file(target) != source_digest:
        target.unlink(missing_ok=True)
        msg = f"input changed while staging: {source}"
        raise RuntimeError(msg)


def _metadata_with_type(
    metadata: Mapping[str, Any] | None, type_: str
) -> dict[str, Any]:
    return {**dict(metadata or {}), "type": type_}

# Copyright (c) 2026 liblaf
"""Closeable record access with explicit retention and reader holds."""

from __future__ import annotations

import fcntl
import json
import uuid
from pathlib import Path
from typing import Any, Self

from ._settings import configured_remote, storage_root
from .records import NotFoundError, Store


class RunAccessor:
    """Read verified assets while holding the source record locally."""

    def __init__(
        self, run_id: str, *, workspace: Path | None = None, store: Store | None = None
    ) -> None:
        self.store = store or Store(storage_root())
        self.store.ensure_initialized()
        self.remote = configured_remote(Path.cwd())
        try:
            self.run_id = self.store.resolve_id(run_id)
        except NotFoundError:
            if self.remote is None:
                raise
            self.remote.import_metadata(self.store)
            self.run_id = self.store.resolve_id(run_id)
        self.reason = "read:" + str(uuid.uuid4())
        self.closed = False
        self.workspace = workspace
        self.store.hold(self.run_id, self.reason)
        try:
            if workspace is not None:
                self._bind_workspace(Path(workspace))
        except BaseException:
            self.store.release_hold(self.run_id, self.reason)
            raise

    def _bind_workspace(self, workspace: Path) -> None:
        config_path = workspace / "analysis.json"
        with (workspace / ".analysis.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            config = json.loads(config_path.read_text())
            reason = "analysis:" + config["workspace_id"]
            acquired = reason not in self.store.projection(self.run_id)["holds"]
            if acquired:
                self.store.hold(self.run_id, reason)
            if self.run_id in config.get("sources", []):
                return
            config["sources"] = sorted(set(config.get("sources", [])) | {self.run_id})
            temporary = workspace / (".analysis-" + str(uuid.uuid4()))
            try:
                temporary.write_text(
                    json.dumps(config, sort_keys=True, indent=2) + "\n"
                )
                temporary.replace(config_path)
            except BaseException:
                if acquired:
                    self.store.release_hold(self.run_id, reason)
                raise
            finally:
                temporary.unlink(missing_ok=True)

    @property
    def record(self) -> dict[str, Any]:
        return self.store.read_record(self.run_id)

    def path(self, relative: str) -> Path:
        if self.closed:
            msg = "record accessor is closed"
            raise RuntimeError(msg)
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            msg = "asset path must be relative and contained"
            raise ValueError(msg)
        files = self.store.read_manifest(self.run_id)["files"]
        selected = [
            entry
            for entry in files
            if entry["path"] == relative
            or entry["path"].startswith(relative.rstrip("/") + "/")
        ]
        bundle_path = self._bundle_path(relative)
        if bundle_path is not None:
            return bundle_path
        if not selected:
            raise FileNotFoundError(relative)
        from .core.assets.bundle import bundles

        for entry in selected:
            local = self._materialize(entry["path"])
            for companion_name, optional in bundles.ls_files(local):
                companion = Path(companion_name)
                if not companion.resolve().is_relative_to(local.parent.resolve()):
                    msg = "asset companion escapes its bundle"
                    raise ValueError(msg)
                logical = companion.relative_to(
                    self.store.root / "runs" / self.run_id
                ).as_posix()
                try:
                    self._materialize(logical)
                except (FileNotFoundError, NotFoundError):
                    if not optional:
                        raise
        return self.store.root / "runs" / self.run_id / relative

    def _bundle_path(self, relative: str) -> Path | None:
        record = self.record["record"]
        tree_bindings = [
            binding
            for binding in [
                *record.get("bundles", []),
                *record.get("input_bindings", []),
            ]
            if binding.get("staged_path", binding.get("path")) == relative.rstrip("/")
            and binding.get("asset_id", "").startswith("sha256-tree:")
        ]
        if tree_bindings:
            try:
                return self.store.materialize_tree_binding(
                    self.run_id, tree_bindings[0]
                )
            except (FileNotFoundError, NotFoundError):
                if self.remote is None:
                    raise
                return self.remote.fetch_tree_binding(
                    self.store, self.run_id, tree_bindings[0]
                )
        return None

    def _materialize(self, relative: str) -> Path:
        try:
            return self.store.materialize(self.run_id, relative)
        except (FileNotFoundError, NotFoundError):
            if self.remote is None:
                raise
            return self.remote.fetch_asset(self.store, self.run_id, relative)

    def close(self) -> None:
        if not self.closed:
            self.store.release_hold(self.run_id, self.reason)
        self.closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def open_run(
    run_id: str, *, workspace: Path | None = None, store: Store | None = None
) -> RunAccessor:
    return RunAccessor(run_id, workspace=workspace, store=store)

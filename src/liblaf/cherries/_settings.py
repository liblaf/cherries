# Copyright (c) 2026 liblaf
"""Project settings shared by the runner and foreground CLI."""

from __future__ import annotations

import os
import tomllib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._remote import Remote
    from .records import Store


def configured_remote(project: Path) -> Remote | None:
    from ._remote import Remote

    config = load_settings(project).get("archive", {}).get("main", {})
    return Remote(config["path"]) if config.get("path") else None


def project_directory(project_dir: Path | None = None) -> Path:
    path = (project_dir or Path.cwd()).resolve()
    candidates = [path, *path.parents]
    for candidate in candidates:
        if (candidate / "cherries.toml").exists() or (
            candidate / "cherries.local.toml"
        ).exists():
            return candidate
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return path


def load_settings(project_dir: Path | None = None) -> dict[str, Any]:
    project = project_directory(project_dir)
    result: dict[str, Any] = {}
    for name in ("cherries.toml", "cherries.local.toml"):
        path = project / name
        if not path.exists():
            continue
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key].update(value)
            else:
                result[key] = value
    return result


def storage_root(project_dir: Path | None = None) -> Path:
    project = project_directory(project_dir)
    collection = load_settings(project).get("collection", {})
    configured = os.environ.get("CHERRIES_STORAGE") or collection.get("storage")
    if configured:
        path = Path(configured).expanduser()
        return (project / path).resolve() if not path.is_absolute() else path.resolve()
    identity = collection.get("id") or str(uuid.uuid5(uuid.NAMESPACE_URL, str(project)))
    return Path.home() / ".local/share/cherries/collections" / identity


def configured_store(
    project_dir: Path | None = None,
    *,
    root: Path | None = None,
    machine_id: str | None = None,
) -> Store:
    """Build a store using the project's persistent recovery policy.

    Old committed work and pending intents are preserved by default. Setting
    ``collection.auto_recover = true`` authorizes recovery cleanup whenever this
    store is initialized, including nested initialization during reader holds.
    """
    from .records import Store

    collection = load_settings(project_dir).get("collection", {})
    auto_recover = collection.get("auto_recover", False)
    if not isinstance(auto_recover, bool):
        msg = "collection.auto_recover must be a boolean"
        raise TypeError(msg)
    return Store(
        storage_root(project_dir) if root is None else root,
        machine_id=machine_id,
        auto_recover=auto_recover,
    )

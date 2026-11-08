# Copyright (c) 2026 liblaf
"""Resolve a project without initializing or changing its storage."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from ._io import StoreError
from ._store import Project, Store


def settings(project_dir: Path | str | None = None) -> tuple[Path, dict[str, Any]]:
    directory = Path(project_dir or Path.cwd()).resolve()
    if directory.is_file():
        directory = directory.parent
    root = next(
        (
            p
            for p in (directory, *directory.parents)
            if (p / "cherries.toml").exists() or (p / "cherries.local.toml").exists()
        ),
        directory,
    )
    result: dict[str, Any] = {}
    for path in (
        Path.home() / ".config/cherries/config.toml",
        root / "cherries.toml",
        root / "cherries.local.toml",
    ):
        if not path.exists():
            continue
        with path.open("rb") as stream:
            document = tomllib.load(stream)
        if document.get("store", {}).get("path"):
            location = Path(document["store"]["path"]).expanduser()
            document["store"]["path"] = str(
                location if location.is_absolute() else path.parent / location
            )
        for key, value in document.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key].update(value)
            else:
                result[key] = value
    return root, result


def configured_store(
    project_dir: Path | str | None = None,
    *,
    store: Store | Path | str | None = None,
) -> Store:
    _, config = settings(project_dir)
    location = (
        store or os.environ.get("CHERRIES_STORE") or config.get("store", {}).get("path")
    )
    location = location or Path.home() / ".local/share/cherries"
    return location if isinstance(location, Store) else Store.open(Path(location))


def configured_project(
    project_dir: Path | str | None = None,
    *,
    store: Store | Path | str | None = None,
    project: str | Project | None = None,
) -> Project:
    if isinstance(project, Project):
        return project
    root, config = settings(project_dir)
    selected_store = configured_store(project_dir, store=store)
    identity = (
        project
        or os.environ.get("CHERRIES_PROJECT")
        or config.get("project", {}).get("id")
    )
    if not identity:
        message = (
            "no project selected; use --project, CHERRIES_PROJECT, or [project].id"
        )
        raise StoreError(message)
    selected = selected_store.projects.get(str(identity))
    if (root / ".git").exists():
        selected = selected.with_repository(root)
    selected.settings = config
    return selected

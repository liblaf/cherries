# Copyright (c) 2026 liblaf
"""Explicit additive import of old records, preserving their evidence limits."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from liblaf.cherries.records import Store as LegacyStore

from ._io import (
    ConflictError,
    IntegrityError,
    contained,
    files,
    hash_file,
    identifier,
    read_yaml,
    write_yaml,
)
from ._store import Project, Result, Store, parse_pointer


def inspect_source(source: str | Path) -> Result:
    """Inspect recognized source layouts without initialization or cleanup."""
    source = Path(source).expanduser().resolve(strict=True)
    if (source / "store.yaml").is_file():
        store = Store.open(source)
        return Result(
            format="cherries-run-store",
            source=str(source),
            runs=[
                {
                    "project": project.id,
                    "id": run.id,
                    "status": run.metadata.get("status"),
                }
                for project in store.projects
                for run in project.runs
            ],
        )
    if (source / "collection.json").is_file():
        legacy = LegacyStore(source, auto_recover=False)
        runs = []
        for run_id in legacy.list_records():
            record = legacy.read_record(run_id)
            legacy.read_manifest(run_id)
            runs.append({"id": run_id, "parents": record.get("parents", [])})
        return Result(format="legacy-collection", source=str(source), runs=runs)
    roots = (
        list((source / "projects").iterdir())
        if (source / "projects").is_dir()
        else [source]
    )
    runs = []
    for project in roots:
        root = project / "runs"
        for folder in sorted(root.iterdir()) if root.is_dir() else []:
            if (folder / "run.yaml").is_file():
                metadata = read_yaml(folder / "run.yaml")
                runs.append(
                    {
                        "project": project.name,
                        "id": metadata.get("id", folder.name.removesuffix(".tmp")),
                        "status": metadata.get("status"),
                        "directory": str(folder),
                    }
                )
    if runs:
        return Result(format="migrated-folders", source=str(source), runs=runs)
    message = f"unrecognized import source: {source}"
    raise IntegrityError(message)


def _payload(source: Path, oid: str, size: int) -> Path:
    if not oid.startswith("sha256:") or len(oid) != 71:
        message = f"legacy file does not have a SHA-256 payload: {oid}"
        raise IntegrityError(message)
    digest = oid[7:]
    root = source / "objects/sha256"
    candidates = [root / digest[:2] / digest]
    candidates.extend((root / digest[:2] / digest[2:4]).glob(digest + ".*"))
    matches = [p for p in candidates if p.is_file() and not p.name.endswith(".tmp")]
    if len(matches) != 1 or hash_file(matches[0]) != (oid, size):
        message = f"legacy payload is missing or invalid: {oid}"
        raise IntegrityError(message)
    return matches[0]


def _legacy_plan(source: Path, ids: list[str] | None) -> list[dict[str, Any]]:
    legacy = LegacyStore(source, auto_recover=False)
    wanted = ids if ids is not None else legacy.list_records()
    visiting: set[str] = set()
    plans: dict[str, dict] = {}

    def visit(run_id: str) -> None:
        identifier(run_id)
        if run_id in plans:
            return
        if run_id in visiting:
            message = f"legacy parent cycle: {run_id}"
            raise IntegrityError(message)
        visiting.add(run_id)
        record = legacy.read_record(run_id)
        manifest = legacy.read_manifest(run_id)
        for parent in record.get("parents", []):
            visit(parent)
        entries = []
        for entry in manifest["files"]:
            payload = _payload(source, entry["asset_id"], entry["size"])
            logical = entry["path"]
            if logical == "run.yaml" or logical.startswith("legacy/"):
                logical = "legacy/files/" + logical
            # Pointer documents are historical control evidence, never CAS payloads.
            if parse_pointer(payload):
                logical = "legacy/pointers/" + logical
            entries.append((logical, payload))
        plans[run_id] = {
            "id": run_id,
            "metadata": record.get("record", {}),
            "record": record,
            "manifest": manifest,
            "files": entries,
            "projection": legacy.projection(run_id),
        }
        visiting.remove(run_id)

    for run_id in wanted:
        visit(run_id)
    return list(plans.values())


def _folder_plan(  # noqa: C901 - reconcile both pointer and inline migrated files
    project: Project, source: Path, info: Result, ids: list[str] | None
) -> list[dict]:
    candidates = {
        entry["id"]: entry for entry in info["runs"] if entry["project"] == project.id
    }
    wanted = list(candidates) if ids is None else list(ids)
    for run_id in wanted:
        if run_id not in candidates:
            message = f"migrated run not found: {project.id}/{run_id}"
            raise IntegrityError(message)
        metadata = read_yaml(Path(candidates[run_id]["directory"]) / "run.yaml")
        for parent in _parents(metadata, project.id):
            if (
                parent["project"] == project.id
                and parent["run"] in candidates
                and parent["run"] not in wanted
            ):
                wanted.append(parent["run"])
    plans = []
    for run_id in wanted:
        entry = candidates[run_id]
        folder = Path(entry["directory"])
        metadata = read_yaml(folder / "run.yaml")
        if folder.name.endswith(".tmp"):
            message = (
                f"unpublished migrated work requires explicit reconciliation: {folder}"
            )
            raise ConflictError(message)
        entries = []
        store_root = (
            folder.parents[3]
            if folder.parent.parent.parent.name == "projects"
            else source
        )
        if not (store_root / "objects").is_dir():
            store_root = source
        for path in files(folder):
            logical = path.relative_to(folder).as_posix()
            if logical == "run.yaml":
                continue
            if logical.startswith("legacy/"):
                logical = "legacy/files/" + logical
            pointer = (
                parse_pointer(path)
                if logical.split("/")[0] in {"inputs", "outputs", "figs"}
                else None
            )
            if pointer:
                entries.append(
                    (logical.removesuffix(".lfs"), _payload(store_root, *pointer))
                )
            else:
                entries.append((logical, path))
        plans.append(
            {
                "id": identifier(str(entry["id"])),
                "metadata": metadata,
                "record": metadata,
                "manifest": {},
                "projection": {},
                "files": entries,
            }
        )
    return plans


def _parents(metadata: dict, default_project: str) -> list[dict[str, str]]:
    result = []
    for parent in [*metadata.get("parents", []), *metadata.get("sources", [])]:
        if isinstance(parent, str):
            edge = {"project": default_project, "run": parent}
        elif isinstance(parent, dict) and parent.get("run"):
            edge = {
                "project": parent.get("project", default_project),
                "run": parent["run"],
            }
        else:
            message = f"unrecognized legacy parent identity: {parent!r}"
            raise IntegrityError(message)
        if edge not in result:
            result.append(edge)
    return result


def import_runs(  # noqa: C901, PLR0912 - imports one preflighted batch with explicit provenance
    project: Project, source: str | Path, ids: list[str] | None = None
) -> Result:
    """Import bytes additively; preserve original IDs and incomplete provenance."""
    source = Path(source).expanduser().resolve(strict=True)
    if source == project.store.root or source.is_relative_to(project.store.root):
        message = "import source overlaps target store"
        raise ConflictError(message)
    info = inspect_source(source)
    if info["format"] == "cherries-run-store":
        original = Store.open(source).projects.get(project.id)
        selected = (
            [original.runs.get(run_id) for run_id in ids]
            if ids is not None
            else list(original.runs)
        )
        return Result(
            format=info["format"],
            imported=[run.copy_to(project.store) for run in selected],
        )
    plans = (
        _legacy_plan(source, ids)
        if info["format"] == "legacy-collection"
        else _folder_plan(project, source, info, ids)
    )
    plans = _ordered_plans(plans, project.id)
    # Preflight all identities and source payloads before creating the first run.
    known = {plan["id"] for plan in plans}
    for plan in plans:
        for suffix in ("", ".tmp"):
            if (project.directory / "runs" / (plan["id"] + suffix)).exists():
                message = f"import would overwrite an existing run: {plan['id']}"
                raise ConflictError(message)
        for parent in _parents(plan["record"], project.id):
            if parent["project"] != project.id or parent["run"] not in known:
                project.store.projects.get(parent["project"]).runs.get(parent["run"])
    imported = []
    for plan in plans:
        original = plan["metadata"]
        draft = project.runs.create(
            id=plan["id"],
            name=original.get("name") or plan["id"],
            kind=original.get("kind", "record"),
            parameters=original.get("parameters", original.get("params", {})),
            tags=original.get("tags", []),
        )
        draft.metadata["legacy"] = {
            "format": info["format"],
            "source": str(source),
            "source_stability": "unknown",
            "replay_verified": False,
        }
        draft.metadata["parents"] = _parents(plan["record"], project.id)
        for logical, payload in plan["files"]:
            target = contained(draft.directory, logical)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(payload, target)
        for name, value in (
            ("record", plan["record"]),
            ("manifest", plan["manifest"]),
            ("projection", plan["projection"]),
        ):
            # JSON is a literal audit attachment; sets in old projections become lists.
            target = contained(draft.directory, f"legacy/{name}.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    value,
                    sort_keys=True,
                    indent=2,
                    default=lambda item: (
                        sorted(item) if isinstance(item, set) else str(item)
                    ),
                )
                + "\n"
            )
        for path in (
            (draft.directory / "inputs").rglob("*")
            if (draft.directory / "inputs").is_dir()
            else []
        ):
            if path.is_file():
                stored = project.store.put(
                    path, logical_path=path.relative_to(draft.directory).as_posix()
                )
                oid, size = stored["oid"], stored["size"]
                draft.metadata.setdefault("input_bindings", []).append(
                    {
                        "input": path.relative_to(draft.directory).as_posix(),
                        "oid": oid,
                        "size": size,
                        "consumed": True,
                        "observed_by": "legacy-import",
                    }
                )
        execution = original.get("execution", {})
        execution = (
            execution if isinstance(execution, dict) else {"legacy_status": execution}
        )
        status = original.get("status", execution.get("status", "recorded"))
        if status not in {"succeeded", "failed", "cancelled", "recorded"}:
            status = "recorded"
        draft.metadata["execution"] = {**execution, "observed_by": "legacy-import"}
        write_yaml(draft.directory / "run.yaml", draft.metadata)
        result = draft.save(
            status=status,
            execution=draft.metadata["execution"],
            git={"provenance": "legacy-incomplete", "replay_verified": False},
        )
        imported.append(result.to_dict())
    return Result(
        format=info["format"],
        imported=imported,
        warnings=[
            "Original source evidence is retained under legacy/; executable source recovery is not inferred."
        ],
    )


def _ordered_plans(plans: list[dict], project: str) -> list[dict]:
    remaining = {plan["id"]: plan for plan in plans}
    ordered = []
    visiting = set()

    def visit(run_id: str) -> None:
        if run_id in visiting:
            message = f"legacy source dependency cycle: {run_id}"
            raise IntegrityError(message)
        if run_id not in remaining:
            return
        visiting.add(run_id)
        plan = remaining[run_id]
        for edge in _parents(plan["record"], project):
            if edge["project"] == project:
                visit(edge["run"])
        visiting.remove(run_id)
        ordered.append(remaining.pop(run_id))

    for run_id in list(remaining):
        visit(run_id)
    return ordered

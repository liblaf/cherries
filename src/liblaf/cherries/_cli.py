# Copyright (c) 2026 liblaf
# ruff: noqa: C901, EM101, EM102, PLR0912, PLR0915, TRY003, TRY301
"""The small foreground command interface for Cherries records."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ._remote import Remote, RemoteError
from ._settings import load_settings, storage_root


def _store(root: Path, machine_id: str | None) -> Any:
    from .records import Store

    return Store(root, machine_id=machine_id)


def _storage(args: argparse.Namespace) -> Path:
    return args.storage or storage_root(args.project_dir)


def _collection_id(args: argparse.Namespace) -> str | None:
    if args.collection_id:
        return args.collection_id
    return load_settings(args.project_dir).get("collection", {}).get("id")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        default=lambda item: sorted(item) if isinstance(item, set) else str(item),
    )


def _emit(value: Any, args: argparse.Namespace) -> None:
    if getattr(args, "json", False):
        print(_json(value))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def _optional(store: Any, names: Sequence[str], *args: Any, **kwargs: Any) -> Any:
    for name in names:
        function = getattr(store, name, None)
        if function is not None:
            return function(*args, **kwargs)
    raise RuntimeError(f"record store does not provide any of: {', '.join(names)}")


def _record_path(store: Any, run_id: str) -> Path:
    return Path(store.root) / "records" / run_id


def _remote(args: argparse.Namespace) -> Remote:
    value = getattr(args, "remote", None) or "main"
    settings = load_settings(args.project_dir)
    if value == "main":
        configured = settings.get("archive", {}).get("main", {}).get("path")
        if not configured:
            raise RuntimeError("archive.main.path is not configured")
        value = configured
    return Remote(value, coordinated=bool(getattr(args, "coordinated", False)))


def _asset_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str) and value.startswith(("sha256:", "sha256-tree:")):
        result.add(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            result.update(_asset_ids(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_asset_ids(item))
    return result


def _analysis_config(folder: Path) -> Path:
    return folder / "analysis.json"


def _read_analysis(folder: Path) -> dict[str, Any]:
    path = _analysis_config(folder)
    if not path.is_file():
        raise RuntimeError(f"analysis workspace is not initialized: {folder}")
    return json.loads(path.read_text())


def _write_analysis(folder: Path, config: Mapping[str, Any]) -> None:
    """Atomically replace the editable analysis workspace pointer."""
    target = _analysis_config(folder)
    temporary = folder / f".analysis-{uuid.uuid4()}.json"
    try:
        temporary.write_text(_json(dict(config)) + "\n")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def _analysis_locked(folder: Path) -> Any:
    """Serialize updates to one editable analysis workspace."""
    with (folder / ".analysis.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    store = _store(_storage(args), args.machine_id)
    return dict(store.ensure_initialized(collection_id=_collection_id(args)))


def _import_remote_if_requested(
    store: Any, args: argparse.Namespace
) -> dict[str, int] | None:
    return (
        _remote(args).import_metadata(store) if getattr(args, "remote", None) else None
    )


def _current_quality(store: Any, run_id: str) -> str:
    reviews = store.projection(run_id).get("reviews", [])
    return reviews[-1].get("status", "unreviewed") if reviews else "unreviewed"


def _browse_summary(store: Any, run_id: str) -> dict[str, Any]:
    record = store.read_record(run_id).get("record", {})
    item = dict(store.projection(run_id))
    legacy_notes = [note for note in item.get("notes", []) if note.get("legacy_source")]
    legacy_note = legacy_notes[-1] if legacy_notes else {}
    item.update(
        {
            "quality": _current_quality(store, run_id),
            "kind": record.get("kind", record.get("mode", "record")),
            "name": record.get("name") or legacy_note.get("name"),
            "legacy_origin": record.get("legacy", {}).get("origin"),
            "legacy_source": legacy_note.get("legacy_source"),
        }
    )
    return item


def command_browse(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    if args.failed and args.remote:
        raise RuntimeError(
            "remote failed-attempt import is not implemented; browse failures locally"
        )
    imported = _import_remote_if_requested(store, args)
    if args.failed:
        return {"attempts": store.list_attempts(), "imported": imported}
    records = [_browse_summary(store, run_id) for run_id in store.list_records()]
    if args.quality:
        records = [item for item in records if item["quality"] == args.quality]
    if args.label:
        records = [item for item in records if args.label in item["labels"]]
    if args.asset:
        records = [
            item
            for item in records
            if args.asset
            in {
                file["asset_id"]
                for file in store.read_manifest(item["run_id"])["files"]
            }
            or args.asset in _asset_ids(store.read_record(item["run_id"])["record"])
        ]
    if args.used_in:
        analyses = {
            item["run_id"]
            for item in records
            if store.read_record(item["run_id"])["record"].get("used_in")
            == args.used_in
        }
        sources = {
            parent
            for run_id in analyses
            for parent in store.read_record(run_id).get("parents", [])
        }
        records = [item for item in records if item["run_id"] in analyses | sources]
    if args.search:
        term = args.search.casefold()
        records = [
            item
            for item in records
            if term
            in " ".join(
                str(item.get(key) or "")
                for key in ("name", "legacy_origin", "legacy_source", "kind")
            ).casefold()
        ]
    return {"records": records, "imported": imported} if imported else records


def command_show(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    if args.remote:
        _remote(args).import_metadata(store, args.run_id)
    run_id = store.resolve_id(args.run_id)
    return {
        "record": store.read_record(run_id),
        "manifest": store.read_manifest(run_id),
        "projection": store.projection(run_id),
    }


def command_read(args: argparse.Namespace) -> str:
    store = _store(_storage(args), args.machine_id)
    if args.remote:
        _remote(args).import_metadata(store, args.run_id)
    run_id = store.resolve_id(args.run_id)
    reason = f"read:{uuid.uuid4()}"
    store.hold(run_id, reason)
    try:
        path = (
            _remote(args).fetch_asset(store, run_id, args.path)
            if args.remote
            else store.materialize(run_id, args.path)
        )
        return Path(path).read_text()
    finally:
        store.release_hold(run_id, reason)


def _lease_path(store: Any, lease_id: str) -> Path:
    return Path(store.root) / "leases" / f"{lease_id}.json"


def _materialize_selected_path(
    store: Any, remote: Remote | None, run_id: str, relative: str
) -> Path:
    """Materialize one declared file or directory and its required companions."""
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise RuntimeError("asset path must be relative and contained")
    files = store.read_manifest(run_id)["files"]
    selected = [
        entry
        for entry in files
        if entry["path"] == relative
        or entry["path"].startswith(relative.rstrip("/") + "/")
    ]
    if not selected:
        record = store.read_record(run_id)["record"]
        bindings = [
            binding
            for binding in [
                *record.get("bundles", []),
                *record.get("input_bindings", []),
            ]
            if binding.get("path", binding.get("staged_path")) == relative
            and str(binding.get("asset_id", "")).startswith("sha256-tree:")
        ]
        if not bindings:
            raise RuntimeError(f"asset path is not in record: {relative}")
        tree_id = bindings[0]["asset_id"]
        destination = Path(store.root) / "runs" / run_id / relative
        return (
            Path(remote.fetch_tree(store, tree_id, destination))
            if remote is not None
            else Path(store.materialize_tree(tree_id, destination))
        )

    def materialize(path: str) -> Path:
        return (
            Path(remote.fetch_asset(store, run_id, path))
            if remote is not None
            else Path(store.materialize(run_id, path))
        )

    from .core.assets.bundle import bundles

    for entry in selected:
        local = materialize(entry["path"])
        for companion_name, optional in bundles.ls_files(local):
            companion = Path(companion_name)
            if not companion.resolve().is_relative_to(local.parent.resolve()):
                raise RuntimeError("asset companion escapes its bundle")
            logical = companion.relative_to(
                Path(store.root) / "runs" / run_id
            ).as_posix()
            try:
                materialize(logical)
            except (FileNotFoundError, RuntimeError):
                if not optional:
                    raise
    return Path(store.root) / "runs" / run_id / relative


def command_path(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    if args.release:
        lease = _lease_path(store, args.release)
        if not lease.is_file():
            raise RuntimeError(f"materialization lease is unknown: {args.release}")
        binding = json.loads(lease.read_text())
        if binding.get("owner") != store.machine_id:
            raise RuntimeError("only the owning machine can release this lease")
        store.release_hold(binding["run_id"], f"read:{args.release}")
        lease.unlink()
        return {"lease": args.release, "released": True}
    if not args.run_id or not args.path:
        raise RuntimeError("path requires RUN_ID and a record-relative path")
    if args.remote:
        _remote(args).import_metadata(store, args.run_id)
    run_id = store.resolve_id(args.run_id)
    workspace_hold: str | None = None
    if args.workspace:
        config = _read_analysis(args.workspace)
        sources = list(config["sources"])
        if run_id not in sources:
            workspace_hold = f"analysis:{config['workspace_id']}"
            store.hold(run_id, workspace_hold)
            sources.append(run_id)
            config["sources"] = sources
            try:
                _write_analysis(args.workspace, config)
            except BaseException:
                store.release_hold(run_id, workspace_hold)
                raise
    lease_id = str(uuid.uuid4())
    lease_reason = f"read:{lease_id}"
    if not args.workspace:
        store.hold(run_id, lease_reason)
    try:
        if args.path.startswith("sha256-tree:"):
            if args.path not in _asset_ids(store.read_record(run_id)["record"]):
                raise RuntimeError("tree asset is not declared by the selected record")
            destination = (
                Path(store.root)
                / "cache"
                / "selected"
                / run_id
                / args.path.removeprefix("sha256-tree:")
            )
            result = (
                _remote(args).fetch_tree(store, args.path, destination)
                if args.remote
                else store.materialize_tree(args.path, destination)
            )
        else:
            result = _materialize_selected_path(
                store, _remote(args) if args.remote else None, run_id, args.path
            )
    except BaseException:
        if not args.workspace:
            store.release_hold(run_id, lease_reason)
        raise
    if args.workspace:
        return {
            "run_id": run_id,
            "path": str(result),
            "partial": True,
            "workspace": str(args.workspace),
        }
    lease = _lease_path(store, lease_id)
    lease.parent.mkdir(parents=True, exist_ok=True)
    try:
        lease.write_text(
            _json(
                {
                    "lease_id": lease_id,
                    "run_id": run_id,
                    "owner": store.machine_id,
                    "path": args.path,
                }
            )
            + "\n"
        )
    except BaseException:
        store.release_hold(run_id, lease_reason)
        raise
    return {"run_id": run_id, "path": str(result), "partial": True, "lease": lease_id}


def command_restore(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    run_id = args.run_id if args.remote else store.resolve_id(args.run_id)
    if args.remote:
        path = _remote(args).restore(store, run_id)
    else:
        reader_reason = f"restore:{uuid.uuid4()}"
        store.hold(run_id, reader_reason)
        try:
            path = Path(store.root) / "runs" / run_id
            for file in store.read_manifest(run_id)["files"]:
                store.materialize(run_id, file["path"])
            record = store.read_record(run_id)["record"]
            for binding in [
                *record.get("bundles", []),
                *record.get("input_bindings", []),
            ]:
                asset_id = binding.get("asset_id", "")
                relative = binding.get("staged_path", binding.get("path"))
                if isinstance(relative, str) and asset_id.startswith("sha256-tree:"):
                    store.materialize_tree(asset_id, path / relative)
            store.append_event(
                "location-restored", run_id, {"remote": None, "complete": True}
            )
        finally:
            store.release_hold(run_id, reader_reason)
    return {"run_id": run_id, "path": str(path), "complete": True}


def command_archive(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    remote = _remote(args)
    locations = [remote.archive(store, run_id).__dict__ for run_id in args.run_ids]
    for location in locations:
        store.append_event("location-verified", location["run_id"], location)
    evicted: list[dict[str, Any]] = []
    if args.evict:
        for location in locations:
            result = store.evict_local(location["run_id"], remote_verified=True)
            if not result["allowed"]:
                raise RuntimeError(f"local eviction blocked: {result['blocked']}")
            evicted.append(result)
    return {"locations": locations, "evicted": evicted}


def command_sync(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    remote = _remote(args)
    return {
        "published_events": remote.sync_metadata(Path(store.root)),
        "imported": remote.import_metadata(store),
    }


def command_index(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    imported = _import_remote_if_requested(store, args)
    return {"index": store.rebuild_index(), "imported": imported}


def command_review(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    return _optional(
        store, ("review",), store.resolve_id(args.run_id), args.quality, note=args.note
    )


def command_label(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    run_id = store.resolve_id(args.run_id)
    return [
        store.label(run_id, label, present=args.action == "add")
        for label in args.labels
    ]


def command_mark(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    run_id = store.resolve_id(args.run_id)
    if args.important is not None:
        return store.mark(run_id, important=args.important)
    return store.mark(run_id, keep_local=args.keep_local)


def command_note_or_link(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    payload = Path(args.file).read_text() if hasattr(args, "file") else args.commit
    return store.append_event(
        args.command, store.resolve_id(args.run_id), {"value": payload}
    )


def _active_maintenance_receipt(store: Any) -> dict[str, Any]:
    path = Path(store.root) / "maintenance.json"
    if not path.is_file():
        raise RuntimeError("a local maintenance pause receipt is required")
    receipt = json.loads(path.read_text())
    if receipt.get("machine_id") != store.machine_id:
        raise RuntimeError("maintenance receipt belongs to another machine")
    return receipt


def _plan_digest(store: Any) -> str:
    from .records import canonical_json

    inventory = store.maintenance_inventory()
    return f"sha256:{hashlib.sha256(canonical_json(inventory)).hexdigest()}"


def _write_plan(
    store: Any, plan: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    plan_id = str(uuid.uuid4())
    payload = {
        "format": 1,
        "plan_id": plan_id,
        "machine_id": store.machine_id,
        "maintenance": dict(receipt),
        "inventory_digest": _plan_digest(store),
        "plan": dict(plan),
    }
    directory = Path(store.root) / "plans"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{plan_id}.json"
    path.write_text(_json(payload) + "\n")
    return {"plan_id": plan_id, "path": str(path), **payload}


def command_maintenance(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    if args.action == "pause":
        return store.pause_maintenance()
    if not args.token:
        raise RuntimeError("maintenance resume requires the pause receipt token")
    store.resume_maintenance(args.token)
    return {"resumed": True}


def command_discard_or_prune(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    if args.plan:
        receipt = _active_maintenance_receipt(store)
        plan = (
            store.plan_discard(args.run_id, inventory_complete=True, maintenance=True)
            if args.command == "discard"
            else store.plan_prune(inventory_complete=True, maintenance=True)
        )
        return _write_plan(store, plan, receipt)
    path = Path(args.apply)
    if not path.is_file():
        raise RuntimeError(f"maintenance plan is unavailable: {path}")
    saved = json.loads(path.read_text())
    if saved.get("format") != 1 or saved.get("machine_id") != store.machine_id:
        raise RuntimeError(
            "maintenance plan belongs to another machine or has an unknown format"
        )
    receipt = _active_maintenance_receipt(store)
    if saved.get("maintenance", {}).get("token") != receipt.get("token"):
        raise RuntimeError("maintenance plan is not bound to the active pause receipt")
    if saved.get("inventory_digest") != _plan_digest(store):
        raise RuntimeError(
            "collection inventory changed; create a new maintenance plan"
        )
    plan = saved.get("plan", {})
    if plan.get("action") != args.command or not plan.get("allowed"):
        raise RuntimeError(
            f"maintenance plan is not allowed: {plan.get('blocked', [])}"
        )
    if args.command == "discard":
        if plan.get("run_id") != store.resolve_id(plan.get("run_id", "")):
            raise RuntimeError("discard plan record binding is invalid")
        return store.apply_discard(
            plan["run_id"], inventory_complete=True, maintenance=True
        )
    return store.apply_prune(inventory_complete=True, maintenance=True)


def command_rerun(args: argparse.Namespace) -> dict[str, Any]:
    from ._capture import prepare_replay

    store = _store(_storage(args), args.machine_id)
    if args.close:
        replay = Path(args.close) / "replay.json"
        if not replay.is_file():
            raise RuntimeError(f"replay workspace is not initialized: {args.close}")
        prepared = json.loads(replay.read_text())
        if prepared.get("owner") != store.machine_id:
            raise RuntimeError(
                "only the owning machine can close this replay workspace"
            )
        store.release_hold(prepared["run_id"], prepared["reader_hold"])
        return {"workspace": str(args.close), "closed": True}
    workspace = args.workspace or (
        Path(store.root) / "replays" / f"{args.run_id}-{uuid.uuid4()}"
    )
    prepared = dict(prepare_replay(store, args.run_id, workspace))
    prepared["owner"] = store.machine_id
    Path(workspace, "replay.json").write_text(_json(prepared) + "\n")
    if args.prepare_only:
        return {**prepared, "prepared": True}
    environment = {
        **os.environ,
        "CHERRIES_STORAGE": str(store.root),
        "CHERRIES_PARENT_RUN": prepared["run_id"],
        "CHERRIES_REPLAY_INPUTS": str(prepared["input_mapping"]),
    }
    # Captured projects with a lock replay it exactly; unlocked projects may
    # sync normally. Never inherit an unrelated caller's frozen-mode setting.
    environment.pop("UV_FROZEN", None)
    command = ["uv", "run"]
    if (Path(prepared["project"]) / "uv.lock").is_file():
        command.append("--locked")
    command.extend(
        [
            "--project",
            prepared["project"],
            "python",
            prepared["entrypoint"],
            *prepared["argv"],
        ]
    )
    try:
        completed = subprocess.run(
            command, cwd=prepared["project"], env=environment, check=False
        )
    finally:
        store.release_hold(prepared["run_id"], prepared["reader_hold"])
    if completed.returncode:
        raise RuntimeError(
            f"replay process failed with exit status {completed.returncode}"
        )
    return {**prepared, "prepared": False, "returncode": completed.returncode}


def command_analysis_new(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    folder = args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    sources = [str(store.resolve_id(item)) for item in args.source]
    workspace = str(uuid.uuid4())
    for source in sources:
        store.hold(source, f"analysis:{workspace}")
    _write_analysis(
        folder,
        {
            "workspace_id": workspace,
            "name": args.name,
            "sources": sources,
            "outputs": [],
        },
    )
    return {
        "workspace_id": workspace,
        "name": args.name,
        "folder": str(folder),
        "sources": sources,
    }


def command_analysis_source(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    config = _read_analysis(args.folder)
    source = str(store.resolve_id(args.run_id))
    sources = list(config["sources"])
    if args.action == "add" and source not in sources:
        store.hold(source, f"analysis:{config['workspace_id']}")
        sources.append(source)
    elif args.action == "remove" and source in sources:
        store.release_hold(source, f"analysis:{config['workspace_id']}")
        sources.remove(source)
    config["sources"] = sources
    _write_analysis(args.folder, config)
    return config


def command_analysis_save(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    folder = args.folder.resolve()
    with _analysis_locked(folder):
        config = _read_analysis(folder)
        outputs: list[str] = args.output or list(config.get("outputs", []))
        output_root = (folder / "out").resolve()
        validated: list[tuple[Path, Path]] = []
        for output in outputs:
            relative = Path(output)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
                or relative.parts[0] != "out"
            ):
                raise RuntimeError(
                    f"analysis output must be contained in out/: {output}"
                )
            source = (folder / relative).resolve()
            if not source.is_relative_to(output_root) or not source.is_file():
                raise RuntimeError(
                    f"declared analysis output missing: {folder / relative}"
                )
            validated.append((source, relative.relative_to("out")))

        previous_revision = config.get("latest_record")
        revision = int(config.get("revision", 0)) + 1
        parents = list(config["sources"])
        if previous_revision and previous_revision not in parents:
            parents.append(previous_revision)
        run_id = str(uuid.uuid4())
        work = Path(
            store.start_work(
                run_id,
                metadata={
                    "mode": "analysis",
                    "workspace_id": config["workspace_id"],
                    "name": config.get("name"),
                    "revision": revision,
                    "previous_revision": previous_revision,
                },
            )
        )
        for source, relative in validated:
            destination = work / "outputs" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        for name in ("RUN.md", "analysis.json"):
            source = folder / name
            if source.is_file():
                shutil.copy2(source, work / name)
        source_tree = folder / "src"
        if source_tree.is_dir():
            shutil.copytree(source_tree, work / "source", dirs_exist_ok=True)
        for source in parents:
            store.register_parent(run_id, source)
        record = {
            "mode": "analysis",
            "reproducibility": "lightweight",
            "parents": parents,
            "workspace_id": config["workspace_id"],
            "name": config.get("name"),
            "revision": revision,
            "previous_revision": previous_revision,
            "used_in": args.used_in,
        }
        sealed = dict(store.seal(run_id, record, work))

        # A failed seal must never advance the editable workspace's latest pointer.
        config["latest_record"] = run_id
        config["revision"] = revision
        _write_analysis(folder, config)

        link = {
            "analysis_run": run_id,
            "workspace_id": config["workspace_id"],
            "name": config.get("name"),
            "revision": revision,
            "previous_revision": previous_revision,
        }
        for source in config["sources"]:
            store.append_event("link", source, link)
        return sealed


def command_analysis_close(args: argparse.Namespace) -> Any:
    store = _store(_storage(args), args.machine_id)
    config = _read_analysis(args.folder)
    for source in config["sources"]:
        store.release_hold(source, f"analysis:{config['workspace_id']}")
    return {"workspace_id": config["workspace_id"], "closed": True}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cherries")
    parser.add_argument("--storage", type=Path)
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--machine-id")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--collection-id")
    init.set_defaults(func=command_init)
    browse = sub.add_parser("browse")
    browse.add_argument("--quality")
    browse.add_argument("--label")
    browse.add_argument("--used-in")
    browse.add_argument("--asset")
    browse.add_argument("--failed", action="store_true")
    browse.add_argument("--search")
    browse.add_argument("--remote", nargs="?", const="main")
    browse.add_argument("--coordinated", action="store_true")
    browse.set_defaults(func=command_browse)
    show = sub.add_parser("show")
    show.add_argument("run_id")
    show.add_argument("--remote", nargs="?", const="main")
    show.add_argument("--coordinated", action="store_true")
    show.set_defaults(func=command_show)
    read = sub.add_parser("read")
    read.add_argument("run_id")
    read.add_argument("path")
    read.add_argument("--remote", nargs="?", const="main")
    read.add_argument("--coordinated", action="store_true")
    read.set_defaults(func=command_read)
    path = sub.add_parser("path")
    path.add_argument("run_id", nargs="?")
    path.add_argument("path", nargs="?")
    path.add_argument("--release")
    path.add_argument("--workspace", type=Path)
    path.add_argument("--remote", nargs="?", const="main")
    path.add_argument("--coordinated", action="store_true")
    path.set_defaults(func=command_path)
    restore = sub.add_parser("restore")
    restore.add_argument("run_id")
    restore.add_argument("--remote", nargs="?", const="main")
    restore.add_argument("--coordinated", action="store_true")
    restore.set_defaults(func=command_restore)
    archive = sub.add_parser("archive")
    archive.add_argument("run_ids", nargs="+")
    archive.add_argument("--remote", nargs="?", const="main", default="main")
    archive.add_argument("--coordinated", action="store_true")
    archive.add_argument("--evict", action="store_true")
    archive.set_defaults(func=command_archive)
    sync = sub.add_parser("sync")
    sync.add_argument("--remote", nargs="?", const="main", default="main")
    sync.add_argument("--coordinated", action="store_true")
    sync.set_defaults(func=command_sync)
    index = sub.add_parser("index")
    index_sub = index.add_subparsers(dest="index_command", required=True)
    rebuild = index_sub.add_parser("rebuild")
    rebuild.add_argument("--remote", nargs="?", const="main")
    rebuild.add_argument("--coordinated", action="store_true")
    rebuild.set_defaults(func=command_index)
    review = sub.add_parser("review")
    review.add_argument("run_id")
    review.add_argument("--quality", required=True)
    review.add_argument("--note")
    review.set_defaults(func=command_review)
    label = sub.add_parser("label")
    label.add_argument("action", choices=("add", "remove"))
    label.add_argument("run_id")
    label.add_argument("labels", nargs="+")
    label.set_defaults(func=command_label)
    mark = sub.add_parser("mark")
    mark.add_argument("run_id")
    group = mark.add_mutually_exclusive_group(required=True)
    group.add_argument("--important", action="store_true", default=None)
    group.add_argument("--no-important", action="store_false", dest="important")
    group.add_argument("--keep-local", action="store_true", default=None)
    group.add_argument("--no-keep-local", action="store_false", dest="keep_local")
    mark.set_defaults(func=command_mark)
    for name in ("note", "link"):
        item = sub.add_parser(name)
        item.add_argument("run_id", nargs="?")
        if name == "note":
            item.add_argument("--file", required=True)
        else:
            item.add_argument("--git", dest="commit", required=True)
        item.set_defaults(func=command_note_or_link)
    for name in ("discard", "prune"):
        item = sub.add_parser(name)
        if name == "discard":
            item.add_argument("run_id", nargs="?")
        action = item.add_mutually_exclusive_group(required=True)
        action.add_argument("--plan", action="store_true")
        action.add_argument("--apply")
        item.set_defaults(func=command_discard_or_prune)
    maintenance = sub.add_parser("maintenance")
    maintenance.add_argument("action", choices=("pause", "resume"))
    maintenance.add_argument("token", nargs="?")
    maintenance.set_defaults(func=command_maintenance)
    rerun = sub.add_parser("rerun")
    rerun.add_argument("run_id", nargs="?")
    rerun.add_argument("--prepare-only", action="store_true")
    rerun.add_argument("--workspace", type=Path)
    rerun.add_argument("--close", type=Path)
    rerun.set_defaults(func=command_rerun)
    analysis = sub.add_parser("analysis")
    a_sub = analysis.add_subparsers(dest="analysis_command", required=True)
    new = a_sub.add_parser("new")
    new.add_argument("folder", type=Path)
    new.add_argument("--source", action="append", required=True)
    new.add_argument("--name")
    new.set_defaults(func=command_analysis_new)
    source = a_sub.add_parser("source")
    source.add_argument("folder", type=Path)
    source.add_argument("action", choices=("add", "remove"))
    source.add_argument("run_id")
    source.set_defaults(func=command_analysis_source)
    save = a_sub.add_parser("save")
    save.add_argument("folder", type=Path)
    save.add_argument("--output", action="append")
    save.add_argument("--used-in")
    save.set_defaults(func=command_analysis_save)
    close = a_sub.add_parser("close")
    close.add_argument("folder", type=Path)
    close.set_defaults(func=command_analysis_close)
    return parser


def _normalize_global_flags(argv: Sequence[str] | None) -> list[str] | None:
    values = list(sys.argv[1:] if argv is None else argv)
    prefix: list[str] = []
    index = 0
    flags_with_value = {"--storage", "--project-dir", "--machine-id"}
    while index < len(values):
        value = values[index]
        if value == "--json":
            prefix.append(value)
            values.pop(index)
            continue
        if value in flags_with_value:
            if index + 1 == len(values):
                return values
            prefix.extend(values[index : index + 2])
            del values[index : index + 2]
            continue
        index += 1
    return prefix + values


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_global_flags(argv))
    try:
        _emit(args.func(args), args)
    except (RemoteError, RuntimeError, OSError) as error:
        parser.error(str(error))
    return 0

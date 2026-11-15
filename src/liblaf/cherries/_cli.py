# Copyright (c) 2026 liblaf
"""Manage local and mounted-remote experiment records."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from . import _storage


def build_parser() -> argparse.ArgumentParser:
    """Build the record-management command line."""
    parser = argparse.ArgumentParser(prog="cherries")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--remote", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="List experiment records")
    listing.add_argument("--tag", action="append", default=[])
    listing.add_argument("--param", action="append", default=[])
    listing.add_argument("--search")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--unfinished", action="store_true")
    listing.add_argument("--json", action="store_true")

    show = commands.add_parser("show", help="Show run.yaml")
    show.add_argument("run")
    show.add_argument("--json", action="store_true")

    files = commands.add_parser("files", help="List logical run paths")
    files.add_argument("run")
    files.add_argument("path", nargs="?", default="")
    files.add_argument("--json", action="store_true")

    get = commands.add_parser("get", help="Copy run files to a destination")
    get.add_argument("run")
    get.add_argument("path")
    get.add_argument("--output", type=Path, required=True)
    get.add_argument("--overwrite", action="store_true")

    edit = commands.add_parser("edit", help="Edit run annotations")
    edit.add_argument("run")
    edit.add_argument("--name")
    description = edit.add_mutually_exclusive_group()
    description.add_argument("--description")
    description.add_argument("--clear-description", action="store_true")
    edit.add_argument("--add-tag", action="append", default=[])
    edit.add_argument("--remove-tag", action="append", default=[])
    edit.add_argument("--metadata", action="append", default=[])
    edit.add_argument("--unset-metadata", action="append", default=[])

    add = commands.add_parser("add", help="Save a figure, asset, or report")
    add.add_argument("run")
    add.add_argument("source", type=Path)
    add.add_argument("--as", dest="target", required=True)

    push = commands.add_parser("push", help="Copy a local run to the remote")
    push.add_argument("run")
    pull = commands.add_parser("pull", help="Copy a remote run to the local repo")
    pull.add_argument("run")
    pull.add_argument("--overwrite", action="store_true")

    remove = commands.add_parser("remove", help="Remove the selected run copy")
    remove.add_argument("run")
    gc = commands.add_parser("gc", help="Collect unreferenced storage objects")
    gc.add_argument("--dry-run", action="store_true")
    verify = commands.add_parser("verify", help="Verify record integrity")
    verify.add_argument("run")
    return parser


def _assignments(values: Sequence[str]) -> dict[str, Any]:
    return {key: json.loads(value) for key, value in (v.split("=", 1) for v in values)}


def _local(args: argparse.Namespace) -> _storage.LocalStore:
    return _storage.LocalStore(args.repo or Path.cwd(), args.project_id)


def _remote(args: argparse.Namespace) -> _storage.RemoteStore:
    if args.remote is None:
        message = "--remote is required for push and pull"
        raise ValueError(message)
    project_id = args.project_id
    if project_id is None and args.command != "gc":
        project_id = _local(args).project_id
    return _storage.RemoteStore(args.remote, project_id)


def _selected(args: argparse.Namespace) -> _storage.LocalStore | _storage.RemoteStore:
    return _remote(args) if args.remote is not None else _local(args)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _list(args: argparse.Namespace) -> None:
    parameters = [
        (key, json.loads(value))
        for key, value in (item.split("=", 1) for item in args.param)
    ]
    records = sorted(
        _selected(args).runs(unfinished=args.unfinished),
        key=lambda record: record.id,
        reverse=True,
    )
    matches = []
    for record in records:
        metadata = record.metadata
        if not all(tag in metadata["tags"] for tag in args.tag):
            continue
        if not all(
            key in metadata["params"] and metadata["params"][key] == value
            for key, value in parameters
        ):
            continue
        if args.search is not None and not any(
            args.search in metadata.get(key, "") for key in ("run-name", "description")
        ):
            continue
        matches.append(metadata)
    matches = matches[: args.limit]
    if args.json:
        _print_json(matches)
    else:
        for metadata in matches:
            description = metadata.get("description", "")
            print(f"{metadata['run-id']}\t{metadata['run-name']}\t{description}")


def _execute(args: argparse.Namespace) -> None:  # noqa: C901, PLR0912
    if args.command == "list":
        _list(args)
        return
    if args.command == "push":
        result = _storage.push(_local(args).get(args.run), _remote(args))
        print(result.resolve())
        return
    if args.command == "pull":
        result = _storage.pull(
            _remote(args).get(args.run), _local(args), overwrite=args.overwrite
        )
        print(result.resolve())
        return
    store = _selected(args)
    if args.command == "gc":
        print(yaml.safe_dump(store.gc(dry_run=args.dry_run), sort_keys=False), end="")
        return
    record = store.get(args.run)
    if args.command == "show":
        if args.json:
            _print_json(record.metadata)
        else:
            print((record.directory / "run.yaml").read_text(encoding="utf-8"), end="")
    elif args.command == "files":
        paths = record.files(args.path)
        if args.json:
            _print_json(paths)
        else:
            for path in paths:
                print(path)
    elif args.command == "get":
        print(
            record.get(
                args.path, args.output.resolve(), overwrite=args.overwrite
            ).resolve()
        )
    elif args.command == "edit":
        result = record.edit(
            name=args.name,
            description=args.description,
            clear_description=args.clear_description,
            add_tags=args.add_tag,
            remove_tags=args.remove_tag,
            metadata=_assignments(args.metadata),
            unset_metadata=args.unset_metadata,
        )
        print(result.resolve())
    elif args.command == "add":
        print(record.add(args.source.resolve(), args.target).resolve())
    elif args.command == "remove":
        record.remove()
    elif args.command == "verify":
        record.verify()


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a command, reporting operational failures on stderr."""
    args = build_parser().parse_args(argv)
    try:
        _execute(args)
    except Exception as error:  # noqa: BLE001
        print(f"cherries: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

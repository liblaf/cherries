# Copyright (c) 2026 liblaf
"""Manage local experiment records and Restic remote archives."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from . import _restic, _storage


def build_parser() -> argparse.ArgumentParser:
    """Build the record-management command line."""
    parser = argparse.ArgumentParser(prog="cherries")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--remote")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="List experiment records")
    listing.add_argument("--tag", action="append", default=[])
    listing.add_argument("--param", action="append", default=[])
    listing.add_argument("--search")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--unfinished", action="store_true")
    listing.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="Show run.yaml")
    show.add_argument("run")
    show.add_argument("--json", action="store_true")

    sub.add_parser("path", help="Print the local run directory path").add_argument(
        "run"
    )

    edit = sub.add_parser("edit", help="Edit local run annotations")
    edit.add_argument("run")
    edit.add_argument("--name")
    desc = edit.add_mutually_exclusive_group()
    desc.add_argument("--description")
    desc.add_argument("--clear-description", action="store_true")
    edit.add_argument("--add-tag", action="append", default=[])
    edit.add_argument("--remove-tag", action="append", default=[])
    edit.add_argument("--metadata", action="append", default=[])
    edit.add_argument("--unset-metadata", action="append", default=[])

    add = sub.add_parser("add", help="Save a figure, asset, or report locally")
    add.add_argument("run")
    add.add_argument("source", type=Path)
    add.add_argument("--as", dest="target", required=True)

    for cmd, help_text in (
        ("lineage", "Show runs in the artifact lineage of selected runs"),
        ("prune", "Keep the artifact lineage of selected runs and remove others"),
    ):
        node = sub.add_parser(cmd, help=help_text)
        node.add_argument("runs", nargs="*")
        node.add_argument("--tag", action="append", default=[])
        node.add_argument("--json", action="store_true")
        if cmd == "prune":
            node.add_argument("--unfinished", action="store_true")
            node.add_argument("--dry-run", action="store_true")

    sub.add_parser("push", help="Archive a local run to Restic").add_argument("run")
    pull = sub.add_parser("pull", help="Restore a remote run locally")
    pull.add_argument("run")
    pull.add_argument("--overwrite", action="store_true")

    sub.add_parser("remove", help="Remove the selected run copy").add_argument("run")
    sub.add_parser("verify", help="Verify a local run record").add_argument("run")
    gc = sub.add_parser("gc", help="Deduplicate snapshots and prune the Restic repo")
    gc.add_argument("--dry-run", action="store_true")
    return parser


def _pairs(values: Sequence[str]) -> list[tuple[str, Any]]:
    return [(k, json.loads(v)) for k, v in (item.split("=", 1) for item in values)]


def _local(args: argparse.Namespace) -> _storage.LocalStore:
    return _storage.LocalStore(args.repo or Path.cwd(), args.project_id)


def _remote(args: argparse.Namespace) -> _restic.ResticStore:
    if args.remote is None:
        message = f"--remote is required for {args.command}"
        raise ValueError(message)
    project_id = args.project_id
    if project_id is None and args.command != "gc":
        project_id = _local(args).project_id
    return _restic.ResticStore(args.remote, project_id)


def _store(args: argparse.Namespace) -> _storage.LocalStore | _restic.ResticStore:
    return _remote(args) if args.remote is not None else _local(args)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _print_runs(records: Sequence[dict[str, Any]], *, as_json: bool) -> None:
    if as_json:
        _print_json(list(records))
        return
    for data in records:
        print(f"{data['run-id']}\t{data['run-name']}\t{data.get('description', '')}")


def _run_local_only(args: argparse.Namespace) -> None:
    if args.remote is not None:
        messages = {
            "path": "path is only available for local runs",
            "verify": "Use 'restic check' to verify a remote Restic repository",
            "edit": "Remote Restic snapshots are immutable; edit locally and push",
            "add": "Remote Restic snapshots are immutable; add locally and push",
        }
        raise ValueError(messages[args.command])
    record = _local(args).get(args.run)
    if args.command == "path":
        print(record.directory.resolve())
    elif args.command == "verify":
        record.verify()
    elif args.command == "edit":
        print(
            record.edit(
                name=args.name,
                description=args.description,
                clear_description=args.clear_description,
                add_tags=args.add_tag,
                remove_tags=args.remove_tag,
                metadata=dict(_pairs(args.metadata)),
                unset_metadata=args.unset_metadata,
            ).resolve()
        )
    elif args.command == "add":
        print(record.add(args.source.resolve(), args.target).resolve())


def _print_yaml(value: Any) -> None:
    print(yaml.safe_dump(value, allow_unicode=True, sort_keys=False, indent=2), end="")


def _run_store_command(args: argparse.Namespace) -> None:
    store = _store(args)
    if args.command == "list":
        _print_runs(
            store.list_metadata(
                tags=args.tag,
                params=_pairs(args.param),
                search=args.search,
                limit=args.limit,
                unfinished=args.unfinished,
            ),
            as_json=args.json,
        )
    elif args.command == "show":
        data = store.show(args.run)
        _print_json(data) if args.json else _print_yaml(data)
    elif args.command == "lineage":
        _print_runs(store.lineage(args.runs, tags=args.tag), as_json=args.json)
    elif args.command == "prune":
        plan = store.prune(
            args.runs,
            tags=args.tag,
            unfinished=args.unfinished,
            dry_run=args.dry_run,
        )
        _print_json(plan) if args.json else _print_yaml(plan)
    elif args.command == "remove":
        store.remove(args.run)


def _execute(args: argparse.Namespace) -> None:
    if args.command in {"path", "verify", "edit", "add"}:
        _run_local_only(args)
    elif args.command in {"list", "show", "lineage", "prune", "remove"}:
        _run_store_command(args)
    elif args.command == "push":
        print(_remote(args).push(_local(args).get(args.run)))
    elif args.command == "pull":
        print(
            _remote(args)
            .pull(args.run, _local(args), overwrite=args.overwrite)
            .resolve()
        )
    elif args.command == "gc" and (output := _remote(args).gc(dry_run=args.dry_run)):
        print(output, end="")


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

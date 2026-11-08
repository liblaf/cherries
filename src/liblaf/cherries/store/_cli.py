# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003
"""Foreground commands for the project/run store.

The command layer resolves context and formats results. All authoritative writes
go through the same store objects used by the Python API.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from liblaf.cherries._version import __version__

from ._config import configured_project, configured_store
from ._import import import_runs, inspect_source
from ._io import (
    NotFoundError,
    StoreError,
    contained,
    read_yaml,
    relative_path,
    write_yaml,
)
from ._source import checkout_source, verify_archive
from ._store import Store

_JSON_VERSION = 1
_MUTABLE_METADATA = frozenset({"name", "tags", "description", "extensions"})
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"@import\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)


@dataclasses.dataclass
class _Outcome:
    data: Any
    exit_code: int = 0


def _serializable(value: Any) -> Any:  # noqa: PLR0911 - dispatch over JSON value kinds
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _serializable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_serializable(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return (
            "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
        )
    if hasattr(value, "to_dict"):
        return _serializable(value.to_dict())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _emit(value: Any, args: argparse.Namespace) -> None:
    value = _serializable(value)
    if args.json:
        envelope = {
            "schema_version": _JSON_VERSION,
            "command": args.command_name,
            "data": value,
        }
        if hasattr(args, "index_refreshed_at"):
            envelope["index"] = {"refreshed_at": args.index_refreshed_at}
        print(
            json.dumps(
                envelope,
                allow_nan=False,
                ensure_ascii=False,
            )
        )
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
    if not args.json and hasattr(args, "index_refreshed_at"):
        print(f"Index refreshed at: {args.index_refreshed_at}", file=sys.stderr)


def _store(args: argparse.Namespace) -> Any:
    return configured_store(args.project_dir, store=args.store)


def _project(args: argparse.Namespace) -> Any:
    return configured_project(args.project_dir, store=args.store, project=args.project)


def _run(args: argparse.Namespace) -> Any:
    return _project(args).runs.get(args.run_id)


def _run_data(run: Any) -> dict[str, Any]:
    data = dict(run.to_dict())
    data.setdefault("id", run.id)
    data.setdefault("project", run.project.id)
    data.setdefault("directory", str(run.directory))
    data.setdefault("fingerprint", run.fingerprint)
    return data


def _parameters(args: argparse.Namespace) -> dict[str, Any]:
    values = read_yaml(args.parameters) if args.parameters else {}
    for assignment in args.parameter:
        key, separator, encoded = assignment.partition("=")
        if not separator or not key:
            raise StoreError("--parameter requires NAME=JSON")
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise StoreError(f"invalid JSON parameter {key!r}: {error.msg}") from error
        values[key] = value
    return values


def _create_run(args: argparse.Namespace) -> Any:
    project = _project(args)
    source = project.runs.get(args.source_run) if args.source_run else None
    run = project.runs.create(
        name=args.name,
        kind=args.kind,
        parameters=_parameters(args),
        tags=args.tag,
    )
    if source is not None:
        run.set_source_run(source)
    return run


def _result_outcome(result: Any, *, execution: bool = False) -> _Outcome:
    data = _serializable(result)
    saved = data.get("saved", True) if isinstance(data, Mapping) else True
    exit_code = data.get("exit_code", 0) if isinstance(data, Mapping) else 0
    if not saved and not (isinstance(data, Mapping) and data.get("discarded")):
        return _Outcome(data, 1)
    if execution and exit_code:
        return _Outcome(data, exit_code if exit_code > 0 else 128 - exit_code)
    return _Outcome(data)


def _store_init(args: argparse.Namespace) -> Any:
    store = Store.create(args.path)
    return {"root": store.root, "store": read_yaml(store.root / "store.yaml")}


def _store_verify(args: argparse.Namespace) -> _Outcome:
    result = _store(args).verify(objects=args.objects)
    return _Outcome(result, 0 if result["ok"] else 1)


def _store_gc(args: argparse.Namespace) -> Any:
    return _store(args).gc(dry_run=args.dry_run)


def _store_recover(args: argparse.Namespace) -> _Outcome:
    result = _store(args).recover()
    return _Outcome(result, 0 if result["ok"] else 1)


def _project_data(project: Any) -> dict[str, Any]:
    try:
        repository = project.repository
    except NotFoundError:
        repository = None
    return {
        "id": project.id,
        "directory": project.directory,
        "repository": repository,
        "archive": project.archive,
    }


def _project_add(args: argparse.Namespace) -> Any:
    return _project_data(_store(args).projects.add(args.id, repo=args.repo))


def _project_list(args: argparse.Namespace) -> Any:
    return [_project_data(project) for project in _store(args).projects.list()]


def _selected_project(args: argparse.Namespace) -> Any:
    if args.id:
        return _store(args).projects.get(args.id)
    return _project(args)


def _project_show(args: argparse.Namespace) -> Any:
    project = _selected_project(args)
    return {
        **read_yaml(project.directory / "project.yaml"),
        **_project_data(project),
    }


def _project_verify(args: argparse.Namespace) -> Any:
    return verify_archive(_selected_project(args), offline=args.offline)


def _run_new(args: argparse.Namespace) -> Any:
    return _run_data(_create_run(args))


def _run_exec(args: argparse.Namespace) -> _Outcome:
    if not args.argv:
        raise StoreError("run exec requires a command after --")
    if args.run_id:
        if (
            args.name is not None
            or args.kind is not None
            or args.tag
            or args.parameter
            or args.parameters
            or args.source_run
        ):
            raise StoreError("creation options cannot modify an existing prepared run")
        run = _run(args)
    else:
        if not args.name:
            raise StoreError("run exec requires --name when creating a run")
        args.kind = args.kind or "simulation"
        run = _create_run(args)
    return _result_outcome(run.execute(args.argv, cwd=args.cwd), execution=True)


def _run_save(args: argparse.Namespace) -> _Outcome:
    return _result_outcome(_run(args).save(status=args.status))


def _run_recover(args: argparse.Namespace) -> _Outcome:
    result = _store(args).recover(args.run_id)
    return _Outcome(result, 0 if result["ok"] else 1)


def _query_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "tags": args.tag,
        "status": args.status,
        "kind": args.kind,
        "where": args.where,
        "sort": args.sort,
        "limit": args.limit,
    }


def _query_runs(args: argparse.Namespace) -> list[Any]:
    store = _store(args)
    if args.refresh:
        store.index.refresh()
    if args.all_projects:
        rows = store.query(**_query_options(args))
    else:
        project = configured_project(
            args.project_dir, store=store, project=args.project
        )
        rows = project.runs.query(**_query_options(args))
    if args.group == "run" and args.run_command == "list":
        args.index_refreshed_at = store.index.last_refreshed_at
    return rows


def _run_list(args: argparse.Namespace) -> Any:
    return _query_runs(args)


def _run_show(args: argparse.Namespace) -> Any:
    return _run_data(_run(args))


def _run_import(args: argparse.Namespace) -> Any:
    if args.inspect:
        return inspect_source(args.source)
    return import_runs(_project(args), args.source, ids=args.run_ids or None)


def _run_tag(args: argparse.Namespace) -> Any:
    run = _run(args)
    with run.edit() as edit:
        for tag in args.tags:
            if args.tag_action == "add":
                edit.tags.add(tag)
            else:
                edit.tags.discard(tag)
    return _run_data(run)


def _edit_file(path: Path) -> None:
    command = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
    if not command:
        raise StoreError("$VISUAL or $EDITOR must name an editor command")
    subprocess.run([*command, str(path)], stdout=sys.stderr, check=True)


def _run_edit(args: argparse.Namespace) -> Any:
    run = _run(args)
    original = dict(run.metadata)
    with tempfile.TemporaryDirectory(prefix="cherries-edit-") as temporary:
        staged = Path(temporary) / "run.yaml"
        write_yaml(staged, original)
        _edit_file(staged)
        changed = read_yaml(staged)
    fixed_keys = (original.keys() | changed.keys()) - _MUTABLE_METADATA
    if any(original.get(key) != changed.get(key) for key in fixed_keys):
        raise StoreError("run edit changed fixed execution evidence")
    with run.edit() as edit:
        for key in _MUTABLE_METADATA:
            if key in changed:
                edit.metadata[key] = changed[key]
            else:
                edit.metadata.pop(key, None)
    return _run_data(run)


def _run_validate(args: argparse.Namespace) -> Any:
    return _run(args).validate()


def _run_export(args: argparse.Namespace) -> Any:
    return _run(args).export(args.to, with_data=args.with_data)


def _run_copy(args: argparse.Namespace) -> Any:
    if args.replace and not args.expect:
        raise StoreError("--replace requires --expect with the target fingerprint")
    if args.expect and not args.replace:
        raise StoreError("--expect requires --replace")
    expected: str | dict[str, str] | None = None
    if args.expect:
        if len(args.expect) == 1 and "=" not in args.expect[0]:
            expected = args.expect[0]
        else:
            expected = {}
            for item in args.expect:
                identity, separator, digest = item.partition("=")
                if not separator or len(identity.split("/")) != 2 or not digest:
                    raise StoreError("batch --expect requires PROJECT/RUN=FINGERPRINT")
                if identity in expected:
                    raise StoreError(f"duplicate expected fingerprint: {identity}")
                expected[identity] = digest
    target = Store.open(args.to_store)
    project = _project(args)
    return project.store.copy_runs(
        [project.runs.get(run_id) for run_id in args.run_ids],
        target,
        replace=args.replace,
        expected_target=expected,
    )


def _run_delete(args: argparse.Namespace) -> Any:
    selected: list[tuple[str, str]] = []
    if args.run_ids:
        if args.all_projects:
            raise StoreError("explicit run IDs require a project, not --all-projects")
        project = _project(args)
        selected = [(project.id, run_id) for run_id in args.run_ids]
    else:
        if not (args.status or args.tag or args.kind or args.where):
            raise StoreError("run delete requires run IDs or an explicit query filter")
        for row in _query_runs(args):
            data = _serializable(row)
            selected.append((data["project"], data["id"]))
    return _store(args).delete(selected, dry_run=args.dry_run)


def _file_list(args: argparse.Namespace) -> Any:
    return [file.to_dict() for file in _run(args).files()]


def _file_path(args: argparse.Namespace) -> Any:
    return _run(args).file(args.path).materialize()


def _file_get(args: argparse.Namespace) -> Any:
    return _run(args).file(args.path).copy_to(args.to)


def _file_add(args: argparse.Namespace) -> Any:
    run = _run(args)
    if args.from_run:
        if args.source:
            raise StoreError("file add accepts a local source or --from-run")
        if not args.path:
            raise StoreError("--from-run requires --path")
        project = (
            run.project.store.projects.get(args.from_project)
            if args.from_project
            else run.project
        )
        source = project.runs.get(args.from_run).file(args.path).ref()
    else:
        if args.from_project or args.path:
            raise StoreError("--from-project and --path require --from-run")
        if args.source is None:
            raise StoreError("file add requires a source file or --from-run")
        source = args.source
    logical = relative_path(args.destination)
    prepared = run.directory.name.endswith(".tmp")
    if logical.startswith("inputs/"):
        run.project.store.bind_input(run, source, logical, consumed=False)
    elif prepared:
        run.add_file(source, path=logical)
    else:
        with run.edit() as edit:
            edit.add_file(source, path=logical)
    return {"run": run.id, "path": logical}


def _file_remove(args: argparse.Namespace) -> Any:
    run = _run(args)
    with run.edit() as edit:
        edit.remove_file(args.path)
    return {"run": run.id, "removed": args.path}


class _HTMLReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []
        self.in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "style":
            self.in_style = True
        for name, value in attrs:
            if value and name in {"src", "href", "xlink:href", "poster", "data"}:
                self.references.append(value)
            elif value and name == "srcset":
                self.references.extend(_srcset_references(value))
            elif value and name == "style":
                self.references.extend(_css_references(value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.references.extend(_css_references(data))


def _css_references(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return [*(match[1] for match in _CSS_URL.findall(text)), *_CSS_IMPORT.findall(text)]


def _srcset_references(value: str) -> list[str]:
    references = []
    position = 0
    while position < len(value):
        while position < len(value) and (
            value[position].isspace() or value[position] == ","
        ):
            position += 1
        start = position
        while position < len(value) and not value[position].isspace():
            position += 1
        url = value[start:position]
        if url:
            references.append(url.rstrip(","))
        if not url.endswith(","):
            while position < len(value) and value[position] != ",":
                position += 1
    return references


def _report_logical(name: str) -> str:
    name = relative_path(name)
    if name.startswith(("README", "reports/")):
        return name
    return f"reports/{name}"


def _report_assets(args: argparse.Namespace, logical: str) -> dict[str, Path]:
    source = args.source.resolve()
    report_parent = posixpath.dirname(logical)
    assets: dict[str, Path] = {}
    for supplied in args.assets:
        directory = supplied.resolve()
        if not directory.is_dir():
            raise StoreError(f"report assets directory does not exist: {directory}")
        prefix = (
            directory.relative_to(source.parent).as_posix()
            if directory.is_relative_to(source.parent)
            else directory.name
        )
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                relative = posixpath.join(
                    prefix, path.relative_to(directory).as_posix()
                )
                target = relative_path(
                    posixpath.normpath(posixpath.join(report_parent, relative))
                )
                if target == logical:
                    raise StoreError("report asset would replace the report itself")
                if target in assets and assets[target].resolve() != path.resolve():
                    raise StoreError(f"report asset has conflicting sources: {target}")
                assets[target] = path
    return assets


def _validate_html(
    source: Path, logical: str, assets: Mapping[str, Path], run: Any
) -> None:
    parser = _HTMLReferences()
    parser.feed(source.read_text())
    pending = [(logical, reference) for reference in parser.references]
    visited_stylesheets: set[str] = set()
    while pending:
        parent, reference = pending.pop()
        url = urlsplit(reference)
        if url.scheme or url.netloc or not url.path:
            continue
        if url.path.startswith("/"):
            raise StoreError(
                f"HTML resource must use a local relative path: {reference}"
            )
        path = relative_path(
            posixpath.normpath(
                posixpath.join(posixpath.dirname(parent), unquote(url.path))
            )
        )
        if path == logical:
            continue
        candidate = assets.get(path)
        if candidate is None:
            candidate = contained(run.directory, path)
        if not candidate.is_file():
            raise StoreError(
                f"missing local HTML resource: {reference} (expected {path})"
            )
        if path.endswith(".css") and path not in visited_stylesheets:
            visited_stylesheets.add(path)
            pending.extend(
                (path, value) for value in _css_references(candidate.read_text())
            )


def _report_add(args: argparse.Namespace) -> Any:
    run = _run(args)
    name = args.destination or args.source.name
    logical = _report_logical(name)
    assets = _report_assets(args, logical)
    if args.source.suffix.lower() in {".html", ".htm"}:
        _validate_html(args.source, logical, assets, run)
    with run.edit() as edit:
        report = edit.report(name)
        shutil.copyfile(args.source, report)
        for path, source in assets.items():
            edit.add_file(source, path=path, inline=True)
    return {"run": run.id, "report": logical, "assets": sorted(assets)}


def _report_edit(args: argparse.Namespace) -> Any:
    run = _run(args)
    with run.edit() as edit:
        staged = edit.report(args.name)
        _edit_file(staged)
        if staged.suffix.lower() in {".html", ".htm"}:
            _validate_html(staged, _report_logical(args.name), {}, run)
    return {"run": run.id, "report": _report_logical(args.name)}


def _metrics_frame(args: argparse.Namespace) -> Any:
    import polars as pl

    frame = _run(args).metrics.scan()
    if args.name:
        frame = frame.filter(pl.col("name") == args.name)
    return frame


def _metrics_show(args: argparse.Namespace) -> Any:
    return _metrics_frame(args).collect().to_dicts()


def _metrics_export(args: argparse.Namespace) -> Any:
    frame = _metrics_frame(args)
    destination = args.to
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = destination.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        frame.sink_parquet(destination)
    elif suffix in {".jsonl", ".ndjson"}:
        frame.sink_ndjson(destination)
    elif suffix == ".csv":
        frame.sink_csv(destination)
    else:
        raise StoreError(
            "metrics export destination must end in .csv, .parquet, or .jsonl"
        )
    return destination


def _code_show(args: argparse.Namespace) -> Any:
    run = _run(args)
    return {
        "project": run.project.id,
        "run": run.id,
        "git": run.metadata.get("git"),
        "archive": run.project.archive,
    }


def _code_checkout(args: argparse.Namespace) -> Any:
    return checkout_source(_run(args), args.to)


def _index_refresh(args: argparse.Namespace) -> Any:
    return _store(args).index.refresh()


def _index_rebuild(args: argparse.Namespace) -> Any:
    return _store(args).index.rebuild()


def _command(
    subparsers: Any,
    name: str,
    handler: Callable[[argparse.Namespace], Any],
    help_text: str,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text, allow_abbrev=False)
    parser.set_defaults(handler=handler)
    return parser


def _creation_arguments(
    parser: argparse.ArgumentParser, *, execute: bool = False
) -> None:
    parser.add_argument("--name", required=not execute)
    parser.add_argument("--kind", default=None if execute else "record")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument(
        "--parameters", type=Path, help="JSON or YAML parameter mapping"
    )
    parser.add_argument(
        "--parameter", "--param", action="append", default=[], metavar="NAME=JSON"
    )
    parser.add_argument(
        "--source-run", help="record a rerun relationship to an existing run"
    )


def _query_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--status", action="append", default=[])
    parser.add_argument("--kind", action="append", default=[])
    parser.add_argument(
        "--where", help="restricted field comparison and Boolean expression"
    )
    parser.add_argument("--sort", default="-created_at")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--all-projects", action="store_true")
    parser.add_argument("--refresh", action="store_true")


def _run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run_id")


def _store_parser(groups: Any) -> None:
    group = groups.add_parser(
        "store", help="initialize, verify, recover, and collect a store"
    )
    commands = group.add_subparsers(dest="store_command", required=True)
    parser = _command(commands, "init", _store_init, "create an empty store")
    parser.add_argument("path", type=Path)
    parser = _command(
        commands, "verify", _store_verify, "validate authoritative records"
    )
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="check metadata and references (default)",
    )
    parser.add_argument(
        "--objects", action="store_true", help="also hash stored payload bytes"
    )
    parser = _command(commands, "gc", _store_gc, "collect unreferenced CAS objects")
    parser.add_argument("--dry-run", action="store_true")
    _command(
        commands, "recover", _store_recover, "recover interrupted store transactions"
    )


def _project_parser(groups: Any) -> None:
    group = groups.add_parser("project", help="bind and inspect source projects")
    commands = group.add_subparsers(dest="project_command", required=True)
    parser = _command(commands, "add", _project_add, "register a stable project ID")
    parser.add_argument("id")
    parser.add_argument("--repo", type=Path, required=True)
    _command(commands, "list", _project_list, "list registered projects")
    for name, handler, help_text in (
        ("show", _project_show, "show project metadata"),
        ("verify", _project_verify, "verify archived Git and LFS content"),
    ):
        parser = _command(commands, name, handler, help_text)
        parser.add_argument("id", nargs="?")
        if name == "verify":
            parser.add_argument("--git", action="store_true")
            parser.add_argument("--lfs", action="store_true")
            parser.add_argument("--offline", action="store_true")


def _run_parser(groups: Any) -> None:
    group = groups.add_parser("run", help="prepare, execute, query, and edit runs")
    commands = group.add_subparsers(dest="run_command", required=True)
    parser = _command(commands, "new", _run_new, "prepare an unpublished run")
    _creation_arguments(parser)
    parser = _command(
        commands, "exec", _run_exec, "execute argv after -- and publish its result"
    )
    parser.usage = "%(prog)s [RUN_ID] [OPTIONS] -- COMMAND [ARG ...]"
    parser.description = (
        "Execute COMMAND after --, capture its log, and publish the run."
    )
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--cwd", type=Path)
    _creation_arguments(parser, execute=True)
    parser = _command(
        commands, "save", _run_save, "publish manually collected materials"
    )
    _run_arguments(parser)
    parser.add_argument(
        "--status",
        default="recorded",
        choices=["recorded", "succeeded", "failed", "cancelled"],
    )
    for name, handler, help_text in (
        ("recover", _run_recover, "recover a run without restarting computation"),
        ("show", _run_show, "show run metadata"),
        ("edit", _run_edit, "edit staged mutable run metadata with $EDITOR"),
        ("validate", _run_validate, "validate a run and its references"),
    ):
        _run_arguments(_command(commands, name, handler, help_text))
    parser = _command(commands, "list", _run_list, "query runs in the local index")
    _query_arguments(parser)
    parser = _command(
        commands, "import", _run_import, "explicitly inspect or import legacy records"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--run-id", dest="run_ids", action="append", default=[])
    parser.add_argument(
        "--inspect", action="store_true", help="inspect source format without writing"
    )
    tag = commands.add_parser("tag", help="change run tags")
    actions = tag.add_subparsers(dest="tag_action", required=True)
    for action in ("add", "remove"):
        parser = _command(actions, action, _run_tag, f"{action} tags")
        _run_arguments(parser)
        parser.add_argument("tags", nargs="+")
    parser = _command(
        commands, "export", _run_export, "export a run as a standalone directory"
    )
    _run_arguments(parser)
    parser.add_argument("--to", type=Path, required=True)
    parser.add_argument("--with-data", action="store_true")
    parser = _command(
        commands, "copy", _run_copy, "copy runs and source closure to another store"
    )
    parser.add_argument("run_ids", nargs="+")
    parser.add_argument("--to-store", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        help="target fingerprint, or PROJECT/RUN=FINGERPRINT for batch replacement",
    )
    parser = _command(
        commands, "delete", _run_delete, "delete a dependency-checked selection"
    )
    parser.add_argument("run_ids", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    _query_arguments(parser)


def _file_parser(groups: Any) -> None:
    group = groups.add_parser("file", help="read and attach logical run files")
    commands = group.add_subparsers(dest="file_command", required=True)
    parser = _command(
        commands, "list", _file_list, "list logical files and pinned content identity"
    )
    _run_arguments(parser)
    for name, handler, help_text in (
        (
            "path",
            _file_path,
            "materialize a stable ordinary local file and print its path",
        ),
        ("get", _file_get, "copy a logical file to a destination"),
        ("remove", _file_remove, "remove a mutable attachment"),
    ):
        parser = _command(commands, name, handler, help_text)
        _run_arguments(parser)
        parser.add_argument("path")
        if name == "get":
            parser.add_argument("--to", type=Path, required=True)
    parser = _command(
        commands, "add", _file_add, "attach a file or pin an input before execution"
    )
    _run_arguments(parser)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--as", dest="destination", required=True)
    parser.add_argument("--from-run")
    parser.add_argument("--from-project")
    parser.add_argument("--path")


def _report_parser(groups: Any) -> None:
    group = groups.add_parser(
        "report", help="publish ordinary reports and local assets"
    )
    commands = group.add_subparsers(dest="report_command", required=True)
    parser = _command(
        commands, "add", _report_add, "attach a report and its local assets"
    )
    _run_arguments(parser)
    parser.add_argument("source", type=Path)
    parser.add_argument("--as", dest="destination")
    parser.add_argument("--assets", type=Path, action="append", default=[])
    parser = _command(
        commands, "edit", _report_edit, "edit a staged report with $EDITOR"
    )
    _run_arguments(parser)
    parser.add_argument("name")


def _metrics_parser(groups: Any) -> None:
    group = groups.add_parser("metrics", help="inspect and export recorded metric rows")
    commands = group.add_subparsers(dest="metrics_command", required=True)
    for name, handler, help_text in (
        ("show", _metrics_show, "show long-form metric rows"),
        ("export", _metrics_export, "export CSV, Parquet, or JSONL metrics"),
    ):
        parser = _command(commands, name, handler, help_text)
        _run_arguments(parser)
        parser.add_argument("--name")
        if name == "export":
            parser.add_argument("--to", type=Path, required=True)


def _code_parser(groups: Any) -> None:
    group = groups.add_parser("code", help="inspect and restore archived source")
    commands = group.add_subparsers(dest="code_command", required=True)
    parser = _command(
        commands, "show", _code_show, "show the recorded ending source commit"
    )
    _run_arguments(parser)
    parser = _command(
        commands, "checkout", _code_checkout, "restore source without executing it"
    )
    _run_arguments(parser)
    parser.add_argument("--to", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the project/run CLI parser without opening a store."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--store",
        type=Path,
        help="store root; overrides CHERRIES_STORE and configuration",
    )
    parser.add_argument("--project", help="stable project ID")
    parser.add_argument(
        "--project-dir", type=Path, help="source project directory for configuration"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit a versioned JSON envelope"
    )
    groups = parser.add_subparsers(dest="group", required=True)
    for configure in (
        _store_parser,
        _project_parser,
        _run_parser,
        _file_parser,
        _report_parser,
        _metrics_parser,
        _code_parser,
    ):
        configure(groups)
    group = groups.add_parser(
        "index", help="refresh or rebuild the machine-local index"
    )
    commands = group.add_subparsers(dest="index_command", required=True)
    _command(
        commands, "refresh", _index_refresh, "refresh changed authoritative metadata"
    )
    _command(commands, "rebuild", _index_rebuild, "rebuild the disposable local index")
    return parser


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = build_parser()
    prefix = list(argv)
    child: list[str] | None = None
    if "--" in prefix:
        separator = prefix.index("--")
        prefix, child = prefix[:separator], prefix[separator + 1 :]
    globals_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    for name, options in (
        ("--store", {"type": Path}),
        ("--project", {}),
        ("--project-dir", {"type": Path}),
        ("--json", {"action": "store_true"}),
    ):
        globals_parser.add_argument(name, **options)
    context, remaining = globals_parser.parse_known_args(prefix)
    args = parser.parse_args(remaining)
    for name, value in vars(context).items():
        setattr(args, name, value)
    if args.group == "run" and args.run_command == "exec":
        args.argv = child or []
    elif child is not None:
        parser.error("-- followed by a command is only valid for run exec")
    if getattr(args, "limit", None) is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    parts = [args.group]
    for name in (f"{args.group}_command", "tag_action"):
        value = getattr(args, name, None)
        if value:
            parts.append(value)
    args.command_name = " ".join(parts)
    return args


def _emit_error(error: BaseException, args: argparse.Namespace) -> None:
    result = getattr(error, "result", None) or getattr(error, "run_result", None)
    message = str(error) or (
        "interrupted" if isinstance(error, KeyboardInterrupt) else type(error).__name__
    )
    error_data = {"type": type(error).__name__, "message": message}
    if result is not None:
        error_data["result"] = _serializable(result)
    if args.json:
        print(
            json.dumps(
                {
                    "schema_version": _JSON_VERSION,
                    "command": args.command_name,
                    "error": error_data,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
    else:
        print(f"cherries: {message}", file=sys.stderr)
        if result is not None:
            print(json.dumps(_serializable(result)), file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a foreground command and return its process exit status."""
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        value = args.handler(args)
        outcome = value if isinstance(value, _Outcome) else _Outcome(value)
        _emit(outcome.data, args)
    except (StoreError, OSError, ValueError, subprocess.SubprocessError) as error:
        _emit_error(error, args)
        return 1
    except KeyboardInterrupt as error:
        _emit_error(error, args)
        return 130
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

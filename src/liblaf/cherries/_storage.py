# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003
"""Local run records, integrity verification, and artifact-lineage pruning."""

from __future__ import annotations

import errno
import shutil
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from . import _git
from ._io import (
    ARTIFACT_ROLES,
    ArtifactEntry,
    collect_artifacts,
    copy,
    identity,
    mutable,
    read_yaml,
    run_relative_path,
    validate_metadata,
    write_yaml,
)
from ._runtime import METRIC_SCHEMA

_DATE_PATTERN = "????/??/??"
_RUN_PATTERN = _DATE_PATTERN + "/*/run.yaml"


def matches_filters(
    metadata: Mapping[str, Any],
    *,
    tags: Sequence[str] = (),
    params: Sequence[tuple[str, Any]] = (),
    search: str | None = None,
) -> bool:
    """Return whether a run.yaml mapping satisfies all CLI list filters."""
    return (
        all(tag in metadata["tags"] for tag in tags)
        and all(
            key in metadata["params"] and metadata["params"][key] == value
            for key, value in params
        )
        and (
            search is None
            or any(
                search in metadata.get(key, "") for key in ("run-name", "description")
            )
        )
    )


def _producers(records: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    producers: dict[str, set[str]] = defaultdict(set)
    for run_id, metadata in records.items():
        for role in ("outputs", "figs"):
            for entry in metadata["artifacts"][role]:
                if entry["size"] > 0:
                    producers[entry["sha256"]].add(run_id)
    return producers


def resolve_lineage(
    records: Mapping[str, Mapping[str, Any]],
    seed_ids: Iterable[str],
) -> set[str]:
    """Compute the transitive ancestor closure of runs by non-empty artifact SHA-256."""
    producers = _producers(records)
    keep: set[str] = set()
    queue: deque[str] = deque()
    for seed in seed_ids:
        if seed not in records:
            raise FileNotFoundError(seed)
        if seed not in keep:
            keep.add(seed)
            queue.append(seed)
    while queue:
        current = queue.popleft()
        digests = (
            e["sha256"]
            for e in records[current]["artifacts"]["inputs"]
            if e["size"] > 0
        )
        for digest in digests:
            for producer in producers.get(digest, ()):
                if producer not in keep:
                    keep.add(producer)
                    queue.append(producer)
    return keep


def plan_prune(
    records: Mapping[str, Mapping[str, Any]],
    explicit_ids: Sequence[str],
    tags: Sequence[str],
    *,
    require_seeds: bool = True,
) -> tuple[list[str], list[str]]:
    """Return (keep_ids, drop_ids) sorted newest-first from lineage seeds."""
    if not explicit_ids and not tags:
        raise ValueError("Specify at least one run ID or --tag to select lineage seeds")
    seeds = list(explicit_ids)
    if tags:
        seeds.extend(
            run_id
            for run_id, data in records.items()
            if all(tag in data["tags"] for tag in tags)
        )
    if require_seeds and not seeds:
        raise ValueError("No runs matched the given seed selection")
    keep_set = resolve_lineage(records, seeds)
    keep = sorted(keep_set, reverse=True)
    drop = sorted((rid for rid in records if rid not in keep_set), reverse=True)
    return keep, drop


def prune_empty(directory: Path, boundary: Path) -> None:
    """Remove only empty ancestors inside a store, leaving its root intact."""
    while directory != boundary and directory.is_relative_to(boundary):
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            if error.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                break
            raise
        directory = directory.parent


class LocalStore:
    """Records in a source repository's cherries/runs directory."""

    def __init__(self, repo: Path, project_id: str | None = None) -> None:
        self.repo = _git.root(repo)
        self.root = self.repo / "cherries"
        self.project_id = project_id or self.repo.name

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def runs(self, *, unfinished: bool = False) -> list[RunRecord]:
        return [
            RunRecord(path.parent, self)
            for path in self.runs_dir.glob(_RUN_PATTERN)
            if path.parent.name.endswith(".tmp") == unfinished
        ]

    def find(self, name: str) -> Path | None:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise FileNotFoundError(name)
        matches = [
            day / name
            for day in self.runs_dir.glob(_DATE_PATTERN)
            if (day / name / "run.yaml").is_file()
        ]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous run ID: {name}")
        return next(iter(matches), None)

    def get(self, run: str | Path) -> RunRecord:
        candidate = Path(run)
        if (candidate / "run.yaml").is_file():
            return RunRecord(candidate.resolve(), self)
        match = self.find(str(run))
        if match is None:
            raise FileNotFoundError(run)
        return RunRecord(match, self)

    def show(self, run: str | Path) -> dict[str, Any]:
        return self.get(run).metadata

    def remove(self, run: str | Path) -> None:
        self.get(run).remove()

    def list_metadata(
        self,
        *,
        tags: Sequence[str] = (),
        params: Sequence[tuple[str, Any]] = (),
        search: str | None = None,
        limit: int = 20,
        unfinished: bool = False,
    ) -> list[dict[str, Any]]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return []
        records = sorted(
            self.runs(unfinished=unfinished),
            key=lambda r: r.directory.name,
            reverse=True,
        )
        matches: list[dict[str, Any]] = []
        for record in records:
            data = record.metadata
            if matches_filters(data, tags=tags, params=params, search=search):
                matches.append(data)
                if len(matches) >= limit:
                    break
        return matches

    def _completed(self) -> tuple[dict[str, RunRecord], dict[str, dict[str, Any]]]:
        completed: dict[str, RunRecord] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for record in self.runs(unfinished=False):
            data = record.metadata
            run_id = data["run-id"]
            if run_id in completed:
                raise ValueError(f"Ambiguous run ID: {run_id}")
            completed[run_id] = record
            metadata[run_id] = data
        return completed, metadata

    def lineage(
        self,
        runs: Sequence[str | Path] = (),
        *,
        tags: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        _, metadata = self._completed()
        keep, _ = plan_prune(
            metadata,
            [self.get(item).id for item in runs],
            tags,
            require_seeds=False,
        )
        return [metadata[run_id] for run_id in keep]

    def prune(
        self,
        runs: Sequence[str | Path] = (),
        *,
        tags: Sequence[str] = (),
        unfinished: bool = False,
        dry_run: bool = False,
    ) -> dict[str, list[str]]:
        completed, metadata = self._completed()
        keep, drop = plan_prune(metadata, [self.get(item).id for item in runs], tags)
        drop_records = [completed[run_id] for run_id in drop]
        if unfinished:
            drop_records.extend(
                sorted(
                    self.runs(unfinished=True),
                    key=lambda r: r.directory.name,
                    reverse=True,
                )
            )
        removed = [record.directory.name for record in drop_records]
        if not dry_run:
            for record in drop_records:
                record.remove()
        return {"keep": keep, "remove": removed}


@dataclass
class RunRecord:
    """One local run's metadata and ordinary directory."""

    directory: Path
    store: LocalStore

    @property
    def metadata(self) -> dict[str, Any]:
        return read_yaml(self.directory / "run.yaml")

    @property
    def id(self) -> str:
        return self.metadata["run-id"]

    def _require_completed(self) -> None:
        if self.directory.suffix == ".tmp":
            raise ValueError(f"Cannot modify unfinished run: {self.directory}")

    def edit(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        clear_description: bool = False,
        add_tags: Sequence[str] = (),
        remove_tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        unset_metadata: Sequence[str] = (),
    ) -> Path:
        self._require_completed()
        data = self.metadata
        if name is not None:
            data["run-name"] = name
        if description is not None:
            data["description"] = description
        if clear_description:
            data.pop("description", None)
        data["tags"] = list(
            dict.fromkeys(
                [*(t for t in data["tags"] if t not in remove_tags), *add_tags]
            )
        )
        data["metadata"].update(metadata or {})
        for key in unset_metadata:
            data["metadata"].pop(key, None)
        validate_metadata(data, expected_run_id=self.directory.name, unfinished=False)
        write_yaml(self.directory / "run.yaml", data)
        return self.directory

    def add(self, source: Path, target: str) -> Path:
        self._require_completed()
        logical = Path(target)
        if (
            not logical.parts
            or logical.is_absolute()
            or ".." in logical.parts
            or logical.as_posix() != target
            or not mutable(target)
        ):
            raise ValueError(
                f"Execution files are fixed or target is invalid: {target}"
            )
        source = source.resolve()
        if target in {"README.md", "README.html"} and source.is_dir():
            raise ValueError(f"Report target must be a file, not a directory: {target}")
        destination = self.directory / logical
        if logical.parts[0] != "figs":
            return copy(source, destination)
        fig_target = Path(*logical.parts[1:])
        planned_names = (
            [
                (fig_target / f.relative_to(source)).as_posix()
                for f in source.rglob("*")
                if f.is_file()
            ]
            if source.is_dir()
            else [fig_target.as_posix()]
        )
        data = self.metadata
        merged = {entry["name"]: entry for entry in data["artifacts"]["figs"]}
        probe = {
            **merged,
            **{
                name: {"name": name, "sha256": "0" * 64, "size": 0}
                for name in planned_names
            },
        }
        validate_metadata(
            {
                **data,
                "artifacts": {
                    **data["artifacts"],
                    "figs": sorted(probe.values(), key=lambda e: e["name"]),
                },
            },
            expected_run_id=self.directory.name,
            unfinished=False,
        )
        saved = copy(source, destination)
        merged.update(
            {entry["name"]: entry for entry in collect_artifacts(saved, fig_target)}
        )
        data["artifacts"]["figs"] = sorted(merged.values(), key=lambda e: e["name"])
        write_yaml(self.directory / "run.yaml", data)
        return destination

    def remove(self) -> None:
        shutil.rmtree(self.directory)
        prune_empty(self.directory.parent, self.store.root)

    def verify_metadata(
        self, data: Mapping[str, Any] | None = None, *, check_path: bool = True
    ) -> dict[Path, ArtifactEntry]:
        """Check metadata schema and daily partition without reading payloads."""
        loaded = self.metadata if data is None else data
        unfinished = self.directory.suffix == ".tmp"
        artifacts = validate_metadata(
            loaded,
            expected_run_id=self.directory.name.removesuffix(".tmp"),
            unfinished=unfinished,
        )
        if check_path:
            expected = self.store.runs_dir / run_relative_path(
                loaded["run-id"], loaded["start-time"]
            )
            if unfinished:
                expected = expected.with_name(expected.name + ".tmp")
            if self.directory.resolve() != expected.resolve():
                raise ValueError(
                    f"Run directory does not match start-time: {self.directory}"
                )
        return artifacts

    def verify(self, *, check_path: bool = True) -> None:
        """Verify metadata, execution log, metrics schema, src, and artifact hashes."""
        data = self.metadata
        artifacts = self.verify_metadata(data, check_path=check_path)
        if any(
            (self.directory / role).exists() and not (self.directory / role).is_dir()
            for role in ARTIFACT_ROLES
        ):
            raise ValueError("Local artifact roles must be directories")
        actual = {
            path.relative_to(self.directory)
            for role in ARTIFACT_ROLES
            for path in (self.directory / role).rglob("*")
            if path.is_file()
        }
        if actual != set(artifacts):
            raise ValueError("Local artifacts are missing or unlisted")
        for name, entry in artifacts.items():
            physical = self.directory / name
            if not physical.is_file() or identity(physical) != (
                entry.sha256,
                entry.size,
            ):
                raise ValueError(f"Artifact content mismatch: {name}")
        if not (self.directory / "run.log").is_file():
            raise ValueError(f"Missing run.log: {self.directory}")
        metrics = self.directory / "metrics.parquet"
        if metrics.exists() and dict(pl.read_parquet_schema(metrics)) != METRIC_SCHEMA:
            raise ValueError(f"Unexpected metric schema: {metrics}")
        if data["commit"] is not None:
            src_dir = self.directory / "src"
            scripts = (
                [p for p in src_dir.iterdir() if p.is_file() and p.suffix == ".py"]
                if src_dir.is_dir()
                else []
            )
            if len(scripts) != 1:
                raise ValueError(f"Expected one entry script in {src_dir}")

# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, EM102, TRY003
"""Thin Restic archive adapter: one tagged snapshot per archived run."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ._io import load_yaml, run_relative_path, validate_metadata
from ._storage import LocalStore, RunRecord, matches_filters, plan_prune, prune_empty

_HOST = "cherries"
_NAMESPACE_TAG = "cherries"
_PROJECT_PREFIX = "project:"
_RUN_PREFIX = "run:"
_PASSWORD_ENV = (
    "RESTIC_PASSWORD",
    "RESTIC_PASSWORD_FILE",
    "RESTIC_PASSWORD_COMMAND",
)
_REPO_MISSING_EXIT = 10


def _validate_tag(kind: str, value: str) -> str:
    if not value or "," in value or any(ch.isspace() for ch in value):
        raise ValueError(f"Invalid Restic {kind} tag value: {value!r}")
    return value


def _extract_tag(tags: Sequence[str], prefix: str) -> str | None:
    return next((t[len(prefix) :] for t in tags if t.startswith(prefix)), None)


@dataclass(frozen=True)
class Snapshot:
    """One Restic snapshot corresponding to a Cherries run."""

    snapshot_id: str
    time: datetime
    project_id: str
    run_id: str


class ResticStore:
    """Restic repository storing each archived run as one tagged snapshot."""

    def __init__(self, repository: str | Path, project_id: str | None = None) -> None:
        raw = str(repository)
        is_local = ":" not in raw or raw.startswith(("/", "./", "../"))
        self.repository = str(Path(raw).resolve()) if is_local else raw
        self.project_id = (
            _validate_tag("project", project_id) if project_id is not None else None
        )

    def _command(self, *args: str) -> list[str]:
        cmd = ["restic", "-r", self.repository]
        if not any(os.environ.get(name) for name in _PASSWORD_ENV):
            cmd.append("--insecure-no-password")
        return [*cmd, *args]

    def _run(
        self, *args: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            self._command(*args), cwd=cwd, capture_output=True, check=False
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()
            raise RuntimeError(f"restic {args[0]} failed: {detail}")
        return result

    def _raw_snapshots(
        self, *, project_id: str | None = None, run_id: str | None = None
    ) -> list[Snapshot]:
        tags = [_NAMESPACE_TAG]
        selected_project = project_id if project_id is not None else self.project_id
        if selected_project is not None:
            tags.append(f"{_PROJECT_PREFIX}{selected_project}")
        if run_id is not None:
            tags.append(f"{_RUN_PREFIX}{_validate_tag('run', run_id)}")
        raw = self._run("snapshots", "--tag", ",".join(tags), "--json").stdout
        return [
            Snapshot(item["id"], datetime.fromisoformat(item["time"]), pid, rid)
            for item in json.loads(raw.decode("utf-8") or "[]") or []
            if (pid := _extract_tag(item.get("tags") or [], _PROJECT_PREFIX))
            and (rid := _extract_tag(item.get("tags") or [], _RUN_PREFIX))
        ]

    def latest_snapshots(self, *, run_id: str | None = None) -> list[Snapshot]:
        """Return the newest snapshot per (project_id, run_id), newest run ID first."""
        newest: dict[tuple[str, str], Snapshot] = {}
        for snap in self._raw_snapshots(run_id=run_id):
            key = (snap.project_id, snap.run_id)
            if key not in newest or snap.time > newest[key].time:
                newest[key] = snap
        return sorted(newest.values(), key=lambda s: (s.run_id, s.time), reverse=True)

    def _resolve(self, run_id: str) -> Snapshot:
        matches = self.latest_snapshots(run_id=run_id)
        if not matches:
            raise FileNotFoundError(run_id)
        if len(matches) > 1:
            raise ValueError(f"Ambiguous run ID: {run_id}")
        return matches[0]

    def _read_yaml(self, snapshot_id: str) -> dict[str, Any]:
        return load_yaml(
            self._run("dump", snapshot_id, "/run.yaml").stdout.decode("utf-8"),
            f"{snapshot_id}:/run.yaml",
        )

    def show(self, run_id: str) -> dict[str, Any]:
        """Read run.yaml from the latest snapshot for a run ID."""
        return self._read_yaml(self._resolve(run_id).snapshot_id)

    def push(self, run: RunRecord) -> str:
        """Archive a completed local run as one tagged Restic snapshot."""
        if run.directory.suffix == ".tmp":
            raise ValueError(f"Cannot push unfinished run: {run.directory}")
        data = run.metadata
        run.verify_metadata(data)
        project_id = _validate_tag("project", data["project-id"])
        if self.project_id is not None and self.project_id != project_id:
            raise ValueError(
                f"Run project-id {project_id!r} does not match {self.project_id!r}"
            )
        run_id = _validate_tag("run", data["run-id"])
        tags = f"{_NAMESPACE_TAG},{_PROJECT_PREFIX}{project_id},{_RUN_PREFIX}{run_id}"
        args = (
            "backup",
            "--host",
            _HOST,
            "--group-by",
            "tags",
            "--skip-if-unchanged",
            "--tag",
            tags,
            "--json",
            ".",
        )
        run_dir = run.directory.resolve()
        result = self._run(*args, cwd=run_dir, check=False)
        if result.returncode == _REPO_MISSING_EXIT:
            self._run("init")
            result = self._run(*args, cwd=run_dir)
        elif result.returncode != 0:
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()
            raise RuntimeError(f"restic backup failed: {detail}")
        for line in reversed(result.stdout.decode("utf-8").splitlines()):
            if line.strip():
                event = json.loads(line)
                if event.get("message_type") == "summary" and event.get("snapshot_id"):
                    return str(event["snapshot_id"])
        matches = self._raw_snapshots(project_id=project_id, run_id=run_id)
        if not matches:
            raise RuntimeError(f"Restic did not return a snapshot ID for run: {run_id}")
        return max(matches, key=lambda s: s.time).snapshot_id

    def pull(self, run_id: str, local: LocalStore, *, overwrite: bool = False) -> Path:
        """Restore a remote run snapshot into the local repository's daily layout."""
        snap = self._resolve(run_id)
        data = self._read_yaml(snap.snapshot_id)
        validate_metadata(data, expected_run_id=snap.run_id, unfinished=False)
        existing = local.find(snap.run_id)
        destination = local.runs_dir / run_relative_path(
            snap.run_id, data["start-time"]
        )
        conflict = existing or (destination if destination.exists() else None)
        if conflict is not None and not overwrite:
            raise FileExistsError(conflict)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix=".cherries-pull-", dir=destination.parent
            ) as temp_dir:
                staged = Path(temp_dir) / snap.run_id
                self._run("restore", snap.snapshot_id, "--target", str(staged))
                RunRecord(staged, local).verify(check_path=False)
                if existing is not None and existing != destination:
                    shutil.rmtree(existing)
                    prune_empty(existing.parent, local.root)
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                staged.rename(destination)
        except BaseException:
            prune_empty(destination.parent, local.root)
            raise
        return destination

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
        if unfinished or limit == 0:
            return []
        matches: list[dict[str, Any]] = []
        for snap in self.latest_snapshots():
            data = self._read_yaml(snap.snapshot_id)
            if matches_filters(data, tags=tags, params=params, search=search):
                matches.append(data)
                if len(matches) >= limit:
                    break
        return matches

    def _all_metadata(
        self,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[Snapshot]]]:
        all_snaps: dict[str, list[Snapshot]] = {}
        latest: dict[str, Snapshot] = {}
        for snap in self._raw_snapshots():
            if (
                snap.run_id in latest
                and latest[snap.run_id].project_id != snap.project_id
            ):
                raise ValueError(f"Ambiguous run ID: {snap.run_id}")
            all_snaps.setdefault(snap.run_id, []).append(snap)
            if snap.run_id not in latest or snap.time > latest[snap.run_id].time:
                latest[snap.run_id] = snap
        metadata = {
            rid: self._read_yaml(snap.snapshot_id) for rid, snap in latest.items()
        }
        return metadata, all_snaps

    def lineage(
        self, runs: Sequence[str] = (), *, tags: Sequence[str] = ()
    ) -> list[dict[str, Any]]:
        metadata, _ = self._all_metadata()
        keep, _ = plan_prune(metadata, list(runs), tags, require_seeds=False)
        return [metadata[rid] for rid in keep]

    def prune(
        self,
        runs: Sequence[str] = (),
        *,
        tags: Sequence[str] = (),
        unfinished: bool = False,  # noqa: ARG002 - common store interface
        dry_run: bool = False,
    ) -> dict[str, list[str]]:
        metadata, all_snaps = self._all_metadata()
        keep, drop = plan_prune(metadata, list(runs), tags)
        drop_snaps = [s.snapshot_id for rid in drop for s in all_snaps[rid]]
        if not dry_run and drop_snaps:
            self._run("forget", "--prune", *drop_snaps)
        return {"keep": keep, "remove": drop}

    def remove(self, run_id: str) -> None:
        snaps = self._raw_snapshots(run_id=run_id)
        if not snaps:
            raise FileNotFoundError(run_id)
        if len({snap.project_id for snap in snaps}) > 1:
            raise ValueError(f"Ambiguous run ID: {run_id}")
        self._run("forget", *(snap.snapshot_id for snap in snaps))

    def gc(self, *, dry_run: bool = False) -> str:
        """Keep the latest snapshot per run and prune unreferenced Restic packs."""
        tag_filter = (
            f"{_NAMESPACE_TAG},{_PROJECT_PREFIX}{self.project_id}"
            if self.project_id is not None
            else _NAMESPACE_TAG
        )
        forget_args = [
            "forget",
            "--tag",
            tag_filter,
            "--group-by",
            "tags",
            "--keep-last",
            "1",
        ]
        extra = ("--dry-run",) if dry_run else ()
        forgotten = self._run(*forget_args, *extra).stdout.decode(
            "utf-8", errors="replace"
        )
        pruned = self._run("prune", *extra).stdout.decode("utf-8", errors="replace")
        return forgotten + pruned

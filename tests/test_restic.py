# Copyright (c) 2026 liblaf
"""Restic remote archive round-trip, tagging, query, lineage, prune, and gc."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries._io import read_yaml, write_yaml
from liblaf.cherries._restic import ResticStore
from liblaf.cherries._storage import LocalStore

needs_restic = pytest.mark.skipif(
    shutil.which("restic") is None, reason="restic is unavailable"
)


def _make_chain_run(
    store: LocalStore,
    run_id: str,
    *,
    tags: list[str] | None = None,
    inputs: dict[str, bytes] | None = None,
    outputs: dict[str, bytes] | None = None,
) -> Path:
    directory = store.runs_dir / "2026/11/15" / run_id
    (directory / "src").mkdir(parents=True)
    (directory / "src/10-run.py").write_text("pass\n")
    (directory / "run.log").write_text("ok\n")
    artifacts: dict[str, list[dict[str, Any]]] = {
        "inputs": [],
        "outputs": [],
        "figs": [],
    }
    for role, files in (("inputs", inputs or {}), ("outputs", outputs or {})):
        for name, payload in sorted(files.items()):
            target = directory / role / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            artifacts[role].append(
                {
                    "name": name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            )
    write_yaml(
        directory / "run.yaml",
        {
            "project-id": store.project_id,
            "run-id": run_id,
            "run-name": run_id,
            "start-time": "2026-11-15 08:00:00+08:00",
            "end-time": "2026-11-15 08:01:00+08:00",
            "tags": list(tags or []),
            "params": {},
            "commit": "a" * 40,
            "metadata": {},
            "artifacts": artifacts,
        },
    )
    return directory


@needs_restic
def test_restic_push_show_repush_and_gc(
    repo: Path, saved: Path, tmp_path: Path
) -> None:
    local = LocalStore(repo)
    run = local.get(saved.name)
    remote = ResticStore(tmp_path / "restic-archive", repo.name)

    first_snap = remote.push(run)
    assert first_snap
    snapshots = remote.latest_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0].run_id == saved.name
    assert snapshots[0].project_id == repo.name

    # Unchanged re-push skips creating a duplicate snapshot.
    assert remote.push(run) == first_snap
    assert len(remote._raw_snapshots(run_id=saved.name)) == 1  # noqa: SLF001

    report = tmp_path / "README.md"
    report.write_text("# Run summary\n")
    run.add(report, "README.md")
    run.edit(description="updated report", add_tags=["checked"])
    second_snap = remote.push(run)
    assert second_snap != first_snap
    assert len(remote._raw_snapshots(run_id=saved.name)) == 2  # noqa: SLF001

    assert remote.show(saved.name)["description"] == "updated report"
    assert [m["run-id"] for m in remote.list_metadata(tags=["checked"])] == [saved.name]

    # Dry-run GC keeps both snapshots; real GC collapses to the latest snapshot.
    remote.gc(dry_run=True)
    assert len(remote._raw_snapshots(run_id=saved.name)) == 2  # noqa: SLF001
    remote.gc()
    assert len(remote._raw_snapshots(run_id=saved.name)) == 1  # noqa: SLF001
    assert remote.latest_snapshots(run_id=saved.name)[0].snapshot_id == second_snap


@needs_restic
def test_restic_pull_preserves_timezone_and_overwrite_semantics(
    repo: Path, saved: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalStore(repo)
    run = local.get(saved.name)
    report = tmp_path / "README.md"
    report.write_text("# Run summary\n")
    run.add(report, "README.md")
    remote = ResticStore(tmp_path / "restic-archive", repo.name)
    remote.push(run)
    original_data = run.metadata
    run.remove()
    try:
        with monkeypatch.context() as changed:
            changed.setenv("TZ", "Pacific/Honolulu")
            time.tzset()
            restored = remote.pull(saved.name, local)
            assert restored == saved
            assert read_yaml(restored / "run.yaml") == original_data
            assert (restored / "README.md").read_text() == "# Run summary\n"
            assert (restored / "outputs/result.txt").read_text() == "shared contents"
            assert (restored / "src/diff.patch").is_file()
            local.get(saved.name).verify()
            with pytest.raises(FileExistsError):
                remote.pull(saved.name, local)
            assert remote.pull(saved.name, local, overwrite=True) == saved
    finally:
        time.tzset()


@needs_restic
def test_restic_lineage_prune_and_remove(repo: Path, tmp_path: Path) -> None:
    local = LocalStore(repo)
    remote = ResticStore(tmp_path / "restic-archive", repo.name)
    mesh = b"mesh data"
    result = b"result data"

    r1 = "00000000-0000-7000-8000-000000000001"
    r2 = "00000000-0000-7000-8000-000000000002"
    r3 = "00000000-0000-7000-8000-000000000003"
    _make_chain_run(local, r1, outputs={"mesh.vtu": mesh})
    _make_chain_run(
        local,
        r2,
        tags=["selected"],
        inputs={"mesh.vtu": mesh},
        outputs={"res.vtu": result},
    )
    _make_chain_run(local, r3, outputs={"trash.vtu": b"unused"})
    for run_id in (r1, r2, r3):
        remote.push(local.get(run_id))

    lineage = [item["run-id"] for item in remote.lineage(tags=["selected"])]
    assert lineage == [
        "00000000-0000-7000-8000-000000000002",
        "00000000-0000-7000-8000-000000000001",
    ]

    dry = remote.prune(tags=["selected"], dry_run=True)
    assert dry == {
        "keep": lineage,
        "remove": ["00000000-0000-7000-8000-000000000003"],
    }
    assert len(remote.latest_snapshots()) == 3

    assert remote.prune(tags=["selected"]) == dry
    assert [snap.run_id for snap in remote.latest_snapshots()] == lineage

    remote.remove("00000000-0000-7000-8000-000000000001")
    assert [snap.run_id for snap in remote.latest_snapshots()] == [
        "00000000-0000-7000-8000-000000000002"
    ]


def test_push_rejects_mismatched_project_id(
    repo: Path, saved: Path, tmp_path: Path
) -> None:
    remote = ResticStore(tmp_path / "restic-archive", "other-project")
    with pytest.raises(ValueError, match="does not match"):
        remote.push(LocalStore(repo).get(saved.name))


@needs_restic
@pytest.mark.parametrize(
    ("start_time", "date"),
    [
        ("2026-01-01 00:15:00+14:00", Path("2026/01/01")),
        ("2025-12-31 23:45:00-12:00", Path("2025/12/31")),
    ],
)
def test_round_trip_keeps_recorded_local_date_after_timezone_changes(
    repo: Path,
    saved: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_time: str,
    date: Path,
) -> None:
    local = LocalStore(repo)
    data = read_yaml(saved / "run.yaml")
    data.update({"start-time": start_time, "end-time": start_time})
    write_yaml(saved / "run.yaml", data)
    original = local.runs_dir / date / saved.name
    original.parent.mkdir(parents=True, exist_ok=True)
    saved.rename(original)
    remote = ResticStore(tmp_path / "restic", repo.name)
    try:
        with monkeypatch.context() as changed:
            changed.setenv("TZ", "Pacific/Honolulu")
            time.tzset()
            remote.push(local.get(saved.name))
            changed.setenv("TZ", "Pacific/Kiritimati")
            time.tzset()
            local.get(saved.name).remove()
            restored = remote.pull(saved.name, local)
            assert restored == original
            assert local.get(saved.name).metadata == data
            local.get(saved.name).verify()
    finally:
        time.tzset()


@needs_restic
def test_pull_rejects_ambiguous_local_id_before_restore(
    repo: Path, saved: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalStore(repo)
    remote = ResticStore(tmp_path / "restic", repo.name)
    remote.push(local.get(saved.name))

    duplicate = local.runs_dir / "2020/02/29" / saved.name
    shutil.copytree(saved, duplicate)
    data = read_yaml(duplicate / "run.yaml")
    data.update(
        {
            "start-time": "2020-02-29 00:00:00+00:00",
            "end-time": "2020-02-29 00:00:00+00:00",
        }
    )
    write_yaml(duplicate / "run.yaml", data)

    original_run = remote._run  # noqa: SLF001

    def guarded(*args: str, **kwargs: Any) -> Any:
        if args and args[0] == "restore":
            pytest.fail("Ambiguous local ID must be rejected before restore")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(remote, "_run", guarded)
    with pytest.raises(ValueError, match="Ambiguous run ID"):
        remote.pull(saved.name, local, overwrite=True)


def test_restic_store_command_builder_respects_password_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in (
        "RESTIC_PASSWORD",
        "RESTIC_PASSWORD_FILE",
        "RESTIC_PASSWORD_COMMAND",
    ):
        monkeypatch.delenv(var, raising=False)
    store = ResticStore(tmp_path / "archive", "study")
    assert "--insecure-no-password" in store._command("snapshots")  # noqa: SLF001

    monkeypatch.setenv("RESTIC_PASSWORD", "secret")
    assert "--insecure-no-password" not in store._command("snapshots")  # noqa: SLF001

    url_store = ResticStore("sftp:nas:/archive/cherries", "study")
    assert url_store.repository == "sftp:nas:/archive/cherries"

    colon_path = ResticStore(tmp_path / "2026:11" / "archive", "study")
    assert colon_path.repository == str((tmp_path / "2026:11" / "archive").resolve())
    assert colon_path.list_metadata(limit=0) == []
    with pytest.raises(ValueError, match="non-negative"):
        colon_path.list_metadata(limit=-1)

    with pytest.raises(ValueError, match="Invalid Restic project tag"):
        ResticStore(tmp_path / "archive", "bad,name")


def test_latest_snapshots_orders_rfc3339_timestamps_across_offsets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ResticStore(tmp_path / "archive", "study")
    payload = [
        {
            "id": "older-offset",
            "time": "2026-11-22T10:00:00+02:00",  # 08:00:00Z
            "tags": ["cherries", "project:study", "run:r1"],
        },
        {
            "id": "newer-z",
            "time": "2026-11-22T09:00:00Z",  # 09:00:00Z
            "tags": ["cherries", "project:study", "run:r1"],
        },
        {
            "id": "exact-second",
            "time": "2026-11-22T09:00:00Z",
            "tags": ["cherries", "project:study", "run:r2"],
        },
        {
            "id": "half-second-later",
            "time": "2026-11-22T09:00:00.5Z",
            "tags": ["cherries", "project:study", "run:r2"],
        },
    ]
    monkeypatch.setattr(
        store,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["restic"], 0, stdout=json.dumps(payload).encode("utf-8"), stderr=b""
        ),
    )
    by_run = {snap.run_id: snap.snapshot_id for snap in store.latest_snapshots()}
    assert by_run == {"r1": "newer-z", "r2": "half-second-later"}

# Copyright (c) 2026 liblaf
from __future__ import annotations

import shutil
import time
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries import _git, _storage
from liblaf.cherries._io import read_yaml, run_relative_path, write_yaml
from liblaf.cherries._storage import LocalStore, RemoteStore, pull, push


def _pending(
    store: LocalStore | RemoteStore,
    template: dict[str, Any],
    run_id: str,
    start_time: str,
) -> Path:
    data = {
        **template,
        "run-id": run_id,
        "project-id": store.project_id,
        "start-time": start_time,
        "end-time": None,
        "commit": None,
        "artifacts": {"inputs": [], "outputs": [], "figs": []},
    }
    directory = store.runs_dir / run_relative_path(run_id + ".tmp", start_time)
    write_yaml(directory / "run.yaml", data)
    (directory / "run.log").write_text("")
    return directory


@pytest.mark.parametrize(
    ("start_time", "date"),
    [
        ("2026-01-01 00:15:00+14:00", Path("2026/01/01")),
        ("2025-12-31 23:45:00-12:00", Path("2025/12/31")),
    ],
)
def test_round_trip_keeps_recorded_local_date_after_client_timezone_changes(
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
    remote = RemoteStore(tmp_path / "remote", repo.name)
    try:
        with monkeypatch.context() as changed:
            changed.setenv("TZ", "Pacific/Honolulu")
            time.tzset()
            destination = push(local.get(saved.name), remote)
            assert destination == remote.runs_dir / date / saved.name
            changed.setenv("TZ", "Pacific/Kiritimati")
            time.tzset()
            local.get(saved.name).remove()
            restored = pull(remote.get(saved.name), local)
            assert restored == original
            assert local.get(saved.name).metadata == data
            assert (restored / "outputs/result.txt").read_text() == "shared contents"
            local.get(saved.name).verify()
    finally:
        time.tzset()


def test_get_supports_ids_unfinished_ids_paths_and_unselected_remote_projects(
    repo: Path, saved: Path, tmp_path: Path
) -> None:
    local = LocalStore(repo)
    remote = RemoteStore(tmp_path / "remote", repo.name)
    destination = push(local.get(saved.name), remote)
    for store, directory in ((local, saved), (remote, destination)):
        assert store.get(saved.name).directory == directory
        assert store.get(directory).directory == directory
        pending = _pending(
            store,
            local.get(saved.name).metadata,
            "unfinished",
            "2024-02-29 23:59:59+08:00",
        )
        assert store.get("unfinished.tmp").directory == pending
        assert store.get(pending).directory == pending
        assert {run.directory for run in store.runs(unfinished=True)} == {pending}
        assert {run.directory for run in store.runs()} == {directory}
    all_projects = RemoteStore(remote.root)
    assert all_projects.get(saved.name).directory == destination
    assert all_projects.get("unfinished.tmp").directory.parent == (
        remote.runs_dir / "2024/02/29"
    )
    other = RemoteStore(remote.root, "other")
    second = _pending(
        other, local.get(saved.name).metadata, "unfinished", "2023-01-02 00:01:00-05:00"
    )
    assert all_projects.get(second).directory == second
    with pytest.raises(ValueError, match="Ambiguous run ID"):
        all_projects.get("unfinished.tmp")
    assert remote.get("unfinished.tmp").directory != second


@pytest.mark.parametrize("direction", ["push", "pull"])
def test_ambiguous_destination_id_fails_before_git_or_payload_writes(
    repo: Path,
    saved: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    local = LocalStore(repo)
    remote = RemoteStore(tmp_path / "remote", repo.name)
    uploaded = push(local.get(saved.name), remote)
    target = remote if direction == "push" else local
    first = uploaded if direction == "push" else saved
    second = target.runs_dir / "2020/02/29" / saved.name
    shutil.copytree(first, second)
    data = read_yaml(second / "run.yaml")
    data.update(
        {
            "start-time": "2020-02-29 00:00:00+00:00",
            "end-time": "2020-02-29 00:00:00+00:00",
        }
    )
    write_yaml(second / "run.yaml", data)
    before = {
        path: path.read_bytes() for path in target.root.rglob("*") if path.is_file()
    }

    def unexpected(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("Ambiguous destination must be rejected before transfer writes")

    monkeypatch.setattr(_git, "transfer", unexpected)
    monkeypatch.setattr(_storage, "_save_artifact", unexpected)
    with pytest.raises(ValueError, match="Ambiguous run ID"):
        target.get(saved.name)
    transfer = (
        partial(push, local.get(saved), remote)
        if direction == "push"
        else partial(pull, remote.get(uploaded), local)
    )
    with pytest.raises(ValueError, match="Ambiguous run ID"):
        transfer()
    assert {
        path: path.read_bytes() for path in target.root.rglob("*") if path.is_file()
    } == before


@pytest.mark.parametrize("remote_record", [False, True])
def test_remove_prunes_only_empty_dates_and_stops_at_store_boundary(
    repo: Path, saved: Path, tmp_path: Path, *, remote_record: bool
) -> None:
    local = LocalStore(repo)
    data = local.get(saved.name).metadata
    local.get(saved.name).remove()
    store = RemoteStore(tmp_path / "remote", repo.name) if remote_record else local
    first = _pending(store, data, "first", "2026-01-01 00:00:00+00:00")
    same_day = _pending(store, data, "same-day", "2026-01-01 01:00:00+00:00")
    next_day = _pending(store, data, "next-day", "2026-01-02 00:00:00+00:00")
    next_month = _pending(store, data, "next-month", "2026-02-01 00:00:00+00:00")
    boundary = store.runs_dir.parent
    unrelated = boundary / "notes.txt"
    unrelated.write_text("keep project material")
    store.get(first).remove()
    assert same_day.is_dir()
    store.get(same_day).remove()
    assert not first.parent.exists()
    assert next_day.is_dir()
    store.get(next_day).remove()
    assert not (store.runs_dir / "2026/01").exists()
    assert next_month.is_dir()
    unrelated.unlink()
    store.get(next_month).remove()
    assert not store.runs_dir.exists()
    assert boundary.is_dir()
    assert repo.is_dir()


@pytest.mark.parametrize("remote_record", [False, True])
def test_verify_rejects_date_mismatch_before_opening_artifact_payloads(
    repo: Path,
    saved: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    remote_record: bool,
) -> None:
    record = LocalStore(repo).get(saved.name)
    remote = RemoteStore(tmp_path / "remote", repo.name)
    if remote_record:
        push(record, remote)
        record = remote.get(saved.name)
    data = record.metadata
    data["start-time"] = "1999-12-31 23:59:59-12:00"
    write_yaml(record.directory / "run.yaml", data)
    original_open = Path.open

    def no_payload_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        assert remote.root / "objects" not in path.parents
        assert not any(
            record.directory / role in path.parents
            for role in ("inputs", "outputs", "figs")
        )
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_payload_open)
    with pytest.raises(ValueError, match="start-time"):
        record.verify()


@pytest.mark.parametrize("direction", ["push", "pull"])
@pytest.mark.parametrize("fault", ["git", "copy"])
@pytest.mark.parametrize("destination_state", ["absent", "existing", "staging"])
def test_failed_transfer_cleans_new_dates_and_preserves_existing_destinations(
    repo: Path,
    saved: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
    fault: str,
    destination_state: str,
) -> None:
    local = LocalStore(repo)
    remote = RemoteStore(tmp_path / "remote", repo.name)
    source = local.get(saved.name)
    if direction == "pull" or destination_state == "existing":
        push(source, remote)
    if direction == "pull":
        source = remote.get(saved.name)
        if destination_state != "existing":
            local.get(saved.name).remove()
    attachment = tmp_path / "new-report.md"
    attachment.write_text("new material that must be copied during synchronization")
    source.add(attachment, "reports/new-report.md")
    target = remote if direction == "push" else local
    final = target.runs_dir / run_relative_path(
        source.id, source.metadata["start-time"]
    )
    staging = final.with_name(final.name + ".tmp")
    marker = None
    if destination_state != "absent":
        preserved = final if destination_state == "existing" else staging
        preserved.mkdir(parents=True, exist_ok=True)
        marker = preserved / "README.md"
        marker.write_text("preserve previous copy")

    def fail(*_args: Any, **_kwargs: Any) -> None:
        message = "injected transfer failure"
        raise OSError(message)

    if fault == "git":
        monkeypatch.setattr(_git, "transfer", fail)
    else:
        monkeypatch.setattr(_storage, "copy", fail)
    transfer = (
        partial(push, source, remote)
        if direction == "push"
        else partial(pull, source, local)
    )
    with pytest.raises(OSError, match="injected transfer failure"):
        transfer()
    if marker is not None:
        assert marker.read_text() == "preserve previous copy"
        if destination_state == "existing":
            assert (final / "run.yaml").is_file()
            assert not staging.exists()
    else:
        assert not final.exists()
        assert not staging.exists()
        assert not final.parent.exists()
        assert not target.runs_dir.exists()


def test_failed_cas_validation_removes_new_empty_buckets_only(tmp_path: Path) -> None:
    remote = RemoteStore(tmp_path / "remote", "project")
    payload = tmp_path / "payload"
    payload.write_bytes(b"valid retained payload")
    retained = remote.put(payload)
    rejected = remote.object("a" * 64)
    with pytest.raises(ValueError, match="mismatch"):
        remote.put(payload, ("a" * 64, payload.stat().st_size))
    assert not rejected.parent.exists()
    assert retained.read_bytes() == b"valid retained payload"
    assert all(
        any(path.iterdir())
        for path in (remote.root / "objects").rglob("*")
        if path.is_dir()
    )

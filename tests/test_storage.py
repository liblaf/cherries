# Copyright (c) 2026 liblaf
from __future__ import annotations

import hashlib
import shutil
import threading
from pathlib import Path
from typing import IO, Any

import pytest

from liblaf.cherries._io import (
    artifact_entries,
    identity,
    read_yaml,
    run_relative_path,
    write_yaml,
)
from liblaf.cherries._storage import LocalStore, RemoteStore, pull, push

from .conftest import git


def test_remote_round_trip_deduplicates_and_omits_empty_directories(
    repo: Path,
    saved: Path,
    tmp_path: Path,
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    local = LocalStore(repo)
    run = local.get(saved.name)
    assert not (saved / "outputs/bundle/nested/empty").exists()
    # Older local trees may contain empty directories; pushing skips them too.
    (saved / "outputs/bundle/nested/empty").mkdir()
    times = {key: run.metadata[key] for key in ("start-time", "end-time")}
    run.edit(description="checked before upload")
    assert {key: run.metadata[key] for key in times} == times
    destination = push(run, remote)
    stored = remote.get(saved.name)
    assert stored.metadata == run.metadata
    assert {key: stored.metadata[key] for key in times} == times
    assert not any(
        (destination / role).exists() for role in ("inputs", "outputs", "figs")
    )
    assert len(list((remote.root / "objects").glob("sha256/*/*/*"))) == 4
    oid, size = identity(saved / "outputs/result.txt")
    entries = artifact_entries(stored.metadata)
    assert entries[Path("outputs/other.lfs")] == {
        "name": "other.lfs",
        "sha256": oid,
        "size": size,
    }
    empty_oid = hashlib.sha256(b"").hexdigest()
    assert remote.object(empty_oid).is_file()
    assert remote.object(empty_oid).read_bytes() == b""
    assert remote.object(oid).read_text() == "shared contents"
    assert "outputs/other.lfs" in stored.files()
    assert "outputs/result.txt.lfs" not in stored.files()
    stored.verify()
    disallowed = destination / "outputs/empty"
    disallowed.mkdir(parents=True)
    with pytest.raises(ValueError, match="Disallowed remote artifact directory"):
        stored.verify()
    disallowed.rmdir()
    disallowed.parent.rmdir()
    with pytest.raises(FileNotFoundError):
        stored.get("outputs/bundle/nested/empty", tmp_path / "empty-export")
    assert not (tmp_path / "empty-export").exists()
    stored.get("outputs", tmp_path / "export")
    assert (tmp_path / "export/other.lfs").read_text() == "shared contents"
    assert (tmp_path / "export/empty.bin").read_bytes() == b""
    assert (tmp_path / "export/bundle/nested/data.bin").read_bytes() == b"tree data"
    assert not (tmp_path / "export/bundle/nested/empty").exists()
    run.remove()
    restored = pull(stored, local)
    local.get(restored.name).verify()
    assert {key: local.get(restored.name).metadata[key] for key in times} == times
    assert (restored / "outputs/other.lfs").read_text() == "shared contents"
    assert (restored / "outputs/bundle/nested/data.bin").read_bytes() == b"tree data"
    assert not (restored / "outputs/bundle/nested/empty").exists()
    assert not any(path.is_symlink() for path in remote.root.rglob("*"))
    assert (
        git(repo, "rev-parse", f"refs/cherries/runs/{saved.name}")
        == stored.metadata["commit"]
    )


def test_directory_get_reads_one_manifest_snapshot(
    repo: Path,
    saved: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from liblaf.cherries import _storage

    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(LocalStore(repo).get(saved.name), remote)
    stored = remote.get(saved.name)
    original = _storage.read_yaml
    reads = []

    def counted(path: Path) -> dict[str, Any]:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(_storage, "read_yaml", counted)
    stored.get("outputs", tmp_path / "export")
    assert reads == [stored.directory / "run.yaml"]
    assert (tmp_path / "export/result.txt").read_bytes() == b"shared contents"
    assert (tmp_path / "export/bundle/nested/data.bin").read_bytes() == b"tree data"


@pytest.mark.parametrize("operation", ["push", "figure"])
def test_gc_waits_for_payload_and_manifest_publication(  # noqa: PLR0915 - controlled writer/collector synchronization
    repo: Path,
    saved: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    local = LocalStore(repo).get(saved.name)
    figure = tmp_path / "new.png"
    figure.write_bytes(b"new figure not referenced yet")
    if operation == "figure":
        push(local, remote)
    original = remote.put
    copied = threading.Event()
    publish = threading.Event()
    gc_started = threading.Event()
    gc_done = threading.Event()
    errors = []
    gc_results = []

    def paused(source: Path, expected: tuple[str, int] | None = None) -> Path:
        result = original(source, expected)
        copied.set()
        assert publish.wait(10)
        return result

    def writer() -> None:
        try:
            if operation == "figure":
                remote.get(saved.name).add(figure, "figs/new.png")
            else:
                push(local, remote)
        except Exception as error:  # noqa: BLE001 - report worker failures in the test thread
            errors.append(error)

    def collector() -> None:
        gc_started.set()
        try:
            gc_results.append(remote.gc())
        except Exception as error:  # noqa: BLE001 - report worker failures in the test thread
            errors.append(error)
        finally:
            gc_done.set()

    monkeypatch.setattr(remote, "put", paused)
    writing = threading.Thread(target=writer)
    collecting = threading.Thread(target=collector)
    writing.start()
    try:
        assert copied.wait(10)
        collecting.start()
        assert gc_started.wait(10)
        assert not gc_done.wait(0.1)
    finally:
        publish.set()
        writing.join(10)
        if collecting.ident is not None:
            collecting.join(10)
    assert not writing.is_alive()
    assert not collecting.is_alive()
    assert not errors
    assert gc_results == [{"objects": 0, "bytes": 0}]
    remote.get(saved.name).verify()


def test_repeated_sync_updates_only_mutable_materials_and_preserves_unique_files(  # noqa: PLR0915 - repeated upload/download lifecycle
    repo: Path,
    saved: Path,
    tmp_path: Path,
) -> None:
    local = LocalStore(repo)
    remote = RemoteStore(tmp_path / "remote", repo.name)
    run = local.get(saved.name)
    source = tmp_path / "report.md"
    source.write_text("first")
    run.add(source, "README.md")
    assert push(run, remote) == remote.runs_dir / saved.relative_to(local.runs_dir)
    stored = remote.get(saved.name)
    commit = run.metadata["commit"]
    times = {key: run.metadata[key] for key in ("start-time", "end-time")}
    source.write_text("only on remote")
    stored.add(source, "reports/remote.md")
    source.write_text("updated")
    run.add(source, "README.md")
    run.edit(
        name="checked", description="verified", add_tags=["selected"], metadata={"n": 1}
    )
    assert {key: run.metadata[key] for key in times} == times
    changed = run.metadata
    changed.update(
        {
            "start-time": "2020-01-01 00:00:00-05:00",
            "end-time": "2020-01-01 00:01:00-05:00",
        }
    )
    write_yaml(saved / "run.yaml", changed)
    assert push(run, remote) == stored.directory
    assert list(remote.runs_dir.glob("*/*/*/*/run.yaml")) == [
        stored.directory / "run.yaml"
    ]
    assert {key: stored.metadata[key] for key in times} == times
    changed.update(times)
    write_yaml(saved / "run.yaml", changed)
    assert (stored.directory / "README.md").read_text() == "updated"
    assert (stored.directory / "reports/remote.md").read_text() == "only on remote"
    assert stored.metadata["commit"] == commit
    assert stored.metadata["description"] == "verified"
    source.write_text("local-only")
    run.add(source, "reports/local.md")
    source.write_text("remote version")
    stored.add(source, "README.md")
    stored.edit(description="remote annotation")
    assert {key: stored.metadata[key] for key in times} == times
    changed = stored.metadata
    changed.update(
        {
            "start-time": "2021-01-01 00:00:00-07:00",
            "end-time": "2021-01-01 00:01:00-07:00",
        }
    )
    write_yaml(stored.directory / "run.yaml", changed)
    assert pull(stored, local) == saved
    assert {key: run.metadata[key] for key in times} == times
    assert (saved / "README.md").read_text() == "updated"
    assert run.metadata["description"] == "verified"
    assert (saved / "reports/remote.md").exists()
    assert pull(stored, local, overwrite=True) == saved
    assert list(local.runs_dir.glob("*/*/*/*/run.yaml")) == [saved / "run.yaml"]
    assert {key: run.metadata[key] for key in times} == times
    assert (saved / "README.md").read_text() == "remote version"
    assert (saved / "reports/local.md").read_text() == "local-only"
    assert run.metadata["description"] == "remote annotation"
    assert run.metadata["params"] == stored.metadata["params"]
    with pytest.raises(ValueError, match="fixed"):
        run.add(source, "outputs/result.txt")
    assert git(repo, "rev-parse", f"refs/cherries/runs/{saved.name}") == commit


@pytest.mark.parametrize("remote", [False, True])
def test_add_preserves_file_paths_without_empty_directory_placeholders(
    repo: Path, saved: Path, tmp_path: Path, *, remote: bool
) -> None:
    run = LocalStore(repo).get(saved.name)
    if remote:
        store = RemoteStore(tmp_path / "remote", repo.name)
        push(run, store)
        run = store.get(saved.name)
    attachment = tmp_path / "attachment"
    (attachment / "nested/empty").mkdir(parents=True)
    (attachment / "nested/file.txt").write_text("attachment")
    run.add(attachment, "assets/attachment")
    assert (run.directory / "assets/attachment/nested/file.txt").read_text() == (
        "attachment"
    )
    assert not (run.directory / "assets/attachment/nested/empty").exists()
    assert run.files("assets") == ["assets/attachment/nested/file.txt"]


def test_cas_gc_is_global_and_retains_unfinished_manifest_without_payload_reads(
    repo: Path,
    saved: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = LocalStore(repo)
    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(local.get(saved.name), remote)
    stored = remote.get(saved.name)
    retained = stored.metadata["artifacts"]["outputs"][0]
    data = stored.metadata
    data["project-id"] = "other"
    data["run-id"] = "00000000-0000-7000-8000-000000000002"
    other = (
        remote.root
        / "projects/other/runs"
        / run_relative_path(data["run-id"] + ".tmp", data["start-time"])
        / "run.yaml"
    )
    data["artifacts"] = {"inputs": [retained], "outputs": [], "figs": []}
    write_yaml(other, data)
    orphan = tmp_path / "orphan.bin"
    orphan.write_bytes(b"unused payload")
    unused = remote.put(orphan)
    stored.remove()
    original_open = Path.open

    def no_cas_open(path: Path, *args: Any, **kwargs: Any) -> IO[str]:
        assert remote.root / "objects" not in path.parents, (
            "GC must not read CAS payload bytes"
        )
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_cas_open)
    plan = remote.gc(dry_run=True)
    assert plan["objects"] >= 1
    assert unused.exists()
    remote.gc()
    assert not unused.exists()
    assert remote.object(retained["sha256"]).exists()
    other.unlink()
    remote.gc()
    assert not remote.object(retained["sha256"]).exists()
    assert not list((remote.root / "objects/sha256").glob("*"))
    assert not (remote.root / "objects").exists()
    assert (repo / "exp/2026/11/15/example/data/result.txt").exists()


def test_gc_rejects_any_malformed_manifest_before_deletion(
    repo: Path, saved: Path, tmp_path: Path
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(LocalStore(repo).get(saved.name), remote)
    orphan = tmp_path / "orphan"
    orphan.write_bytes(b"orphan")
    payload = remote.put(orphan)
    write_yaml(
        remote.root / "projects/other/runs/2026/11/15/bad.tmp/run.yaml",
        {"artifacts": {}},
    )
    for dry_run in (True, False):
        with pytest.raises(ValueError, match=r"artifact|Artifact"):
            remote.gc(dry_run=dry_run)
        assert payload.exists()


def test_corrupt_payload_fails_readonly_verification_and_get(
    repo: Path,
    saved: Path,
    tmp_path: Path,
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(LocalStore(repo).get(saved.name), remote)
    run = remote.get(saved.name)
    oid = hashlib.sha256(b"shared contents").hexdigest()
    remote.object(oid).write_bytes(b"shared contenTS")
    with pytest.raises(ValueError, match="mismatch"):
        run.verify()
    with pytest.raises(ValueError, match="mismatch"):
        run.get("outputs/result.txt", tmp_path / "out.txt")
    assert not (tmp_path / "out.txt").exists()


def test_get_does_not_replace_destination_only_tmp_sibling(
    repo: Path,
    saved: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / "result.txt.tmp").write_text("keep destination-only file")
    LocalStore(repo).get(saved.name).get("outputs/result.txt", tmp_path / "result.txt")
    assert (tmp_path / "result.txt.tmp").read_text() == "keep destination-only file"


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "../escape", "sha256": "a" * 64, "size": 1},
        {"name": "/absolute", "sha256": "a" * 64, "size": 1},
        {"name": "nested//file", "sha256": "a" * 64, "size": 1},
        {"name": "file", "sha256": "A" * 64, "size": 1},
        {"name": "file", "sha256": "a" * 64, "size": -1},
        {"name": "file", "sha256": "a" * 64, "size": True},
        {"name": "file", "sha256": "a" * 64, "size": 1, "extra": 2},
    ],
)
def test_corrupt_manifest_cannot_be_verified_or_materialized(
    repo: Path, saved: Path, tmp_path: Path, entry: dict
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(LocalStore(repo).get(saved.name), remote)
    record = remote.get(saved.name)
    data = record.metadata
    data["artifacts"]["outputs"] = [entry]
    write_yaml(record.directory / "run.yaml", data)
    with pytest.raises(ValueError, match=r"artifact|Artifact"):
        record.verify()
    with pytest.raises(ValueError, match=r"artifact|Artifact"):
        record.get("outputs", tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("change", ["missing", "changed", "unlisted", "role-file"])
def test_verify_checks_local_manifest_against_real_files(
    repo: Path, saved: Path, change: str
) -> None:
    if change == "missing":
        (saved / "outputs/result.txt").unlink()
    elif change == "changed":
        (saved / "outputs/result.txt").write_text("changed")
    elif change == "unlisted":
        (saved / "outputs/unlisted").write_text("not registered")
    else:
        shutil.rmtree(saved / "outputs")
        (saved / "outputs").write_text("not a role directory")
    with pytest.raises(ValueError, match=r"artifact|Artifact"):
        LocalStore(repo).get(saved.name).verify()


def test_remove_unfinished_remote_copy_before_git_transfer(
    repo: Path,
    saved: Path,
    tmp_path: Path,
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    pending = remote.runs_dir / run_relative_path(
        saved.name + ".tmp", read_yaml(saved / "run.yaml")["start-time"]
    )
    write_yaml(pending / "run.yaml", read_yaml(saved / "run.yaml"))
    assert not remote.git(repo.name).exists()
    remote.get(pending).remove()
    assert not pending.exists()
    assert saved.exists()


def test_verify_detects_missing_execution_log(repo: Path, saved: Path) -> None:
    (saved / "run.log").unlink()
    with pytest.raises(ValueError, match=r"Missing run\.log"):
        LocalStore(repo).get(saved.name).verify()


def test_figs_merge_by_name_while_execution_artifacts_stay_frozen(
    repo: Path, saved: Path, tmp_path: Path
) -> None:
    local = LocalStore(repo)
    run = local.get(saved.name)
    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(run, remote)
    stored = remote.get(saved.name)
    frozen = stored.metadata["artifacts"]["outputs"]
    original = (saved / "outputs/result.txt").read_bytes()
    # A repeated upload must preserve the first published execution manifest,
    # even if the source's file and metadata were manually changed afterward.
    (saved / "outputs/result.txt").write_bytes(b"changed execution")
    changed = run.metadata
    changed["artifacts"]["outputs"] = []
    write_yaml(saved / "run.yaml", changed)
    figure = tmp_path / "figure"
    figure.write_bytes(b"remote-only")
    stored.add(figure, "figs/remote.png")
    figure.write_bytes(b"new local loss")
    run.add(figure, "figs/loss.png")
    figure.write_bytes(b"local-only")
    run.add(figure, "figs/local.png")
    push(run, remote)
    assert stored.metadata["artifacts"]["outputs"] == frozen
    stored.get("outputs/result.txt", tmp_path / "execution")
    assert (tmp_path / "execution").read_bytes() == original
    assert stored.files("figs") == [
        "figs/local.png",
        "figs/loss.png",
        "figs/remote.png",
    ]
    assert not (stored.directory / "figs").exists()
    stored.get("figs", tmp_path / "figures")
    assert (tmp_path / "figures/loss.png").read_bytes() == b"new local loss"
    figure.write_bytes(b"remote replacement")
    stored.add(figure, "figs/loss.png")
    pull(stored, local)
    assert (saved / "figs/loss.png").read_bytes() == b"new local loss"
    assert (saved / "figs/remote.png").read_bytes() == b"remote-only"
    pull(stored, local, overwrite=True)
    assert (saved / "figs/loss.png").read_bytes() == b"remote replacement"
    assert (saved / "figs/local.png").read_bytes() == b"local-only"
    assert run.metadata["artifacts"]["outputs"] == []
    assert (saved / "outputs/result.txt").read_bytes() == b"changed execution"


@pytest.mark.parametrize("remote_record", [False, True])
def test_add_nested_figures_has_no_empty_dirs_or_manifest_sidecars(
    repo: Path, saved: Path, tmp_path: Path, *, remote_record: bool
) -> None:
    run = LocalStore(repo).get(saved.name)
    if remote_record:
        remote = RemoteStore(tmp_path / "remote", repo.name)
        push(run, remote)
        run = remote.get(saved.name)
    source = tmp_path / "figures"
    (source / "nested/empty").mkdir(parents=True)
    (source / "nested/a.lfs").write_bytes(b"literal suffix")
    (source / "nested/zero").write_bytes(b"")
    run.add(source, "figs/bundle")
    assert run.files("figs/bundle") == [
        "figs/bundle/nested/a.lfs",
        "figs/bundle/nested/zero",
    ]
    run.get("figs/bundle", tmp_path / "export")
    assert (tmp_path / "export/nested/a.lfs").read_bytes() == b"literal suffix"
    assert (tmp_path / "export/nested/zero").read_bytes() == b""
    assert not (tmp_path / "export/nested/empty").exists()
    if remote_record:
        assert not (run.directory / "figs").exists()
    run.verify()


def test_corrupt_directory_get_publishes_no_files(
    repo: Path, saved: Path, tmp_path: Path
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(LocalStore(repo).get(saved.name), remote)
    run = remote.get(saved.name)
    oid = artifact_entries(run.metadata)[Path("outputs/result.txt")]["sha256"]
    remote.object(oid).write_bytes(b"corrupt payload")
    with pytest.raises(ValueError, match="mismatch"):
        run.get("outputs", tmp_path / "export")
    assert not (tmp_path / "export").exists()
    target = tmp_path / "existing"
    target.write_bytes(b"preserve existing")
    with pytest.raises(ValueError, match="mismatch"):
        run.get("outputs/result.txt", target, overwrite=True)
    assert target.read_bytes() == b"preserve existing"


def test_normal_cas_reuse_does_not_rehash_existing_payload(
    repo: Path, saved: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from liblaf.cherries import _storage

    remote = RemoteStore(tmp_path / "remote", repo.name)
    run = LocalStore(repo).get(saved.name)
    push(run, remote)
    original_identity = _storage.identity

    def no_remote_hash(path: Path) -> tuple[str, int]:
        assert remote.root / "objects" not in path.parents
        return original_identity(path)

    monkeypatch.setattr(_storage, "identity", no_remote_hash)
    # The second distinct record reuses all four existing payloads.
    metadata = run.metadata
    metadata["run-id"] = "second"
    copied = saved.with_name("second")
    shutil.copytree(saved, copied)
    write_yaml(copied / "run.yaml", metadata)
    git(repo, "update-ref", "refs/cherries/runs/second", metadata["commit"])
    # _git transfers also require the matching fixed LFS source ref when present;
    # fixture source has no native Git LFS payloads.
    push(local_run := LocalStore(repo).get("second"), remote)
    assert remote.get(local_run.id).metadata["artifacts"] == metadata["artifacts"]


def test_remote_get_reads_payload_once_before_local_verification(
    repo: Path, saved: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = RemoteStore(tmp_path / "remote", repo.name)
    push(LocalStore(repo).get(saved.name), remote)
    run = remote.get(saved.name)
    oid = artifact_entries(run.metadata)[Path("outputs/result.txt")]["sha256"]
    payload = remote.object(oid)
    original_open = Path.open
    reads = []

    def track_payload_open(path: Path, *args: Any, **kwargs: Any) -> IO[str]:
        if path == payload:
            reads.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", track_payload_open)
    run.get("outputs/result.txt", tmp_path / "export")
    assert reads == [payload]
    assert (tmp_path / "export").read_text() == "shared contents"

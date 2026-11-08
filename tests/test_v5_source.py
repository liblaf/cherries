# Copyright (c) 2026 liblaf
"""Real Git repositories exercise portable end snapshots and object closure."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from liblaf.cherries.store._io import ConflictError, IntegrityError
from liblaf.cherries.store._source import (
    archive_snapshot,
    checkout_source,
    copy_archive,
    fingerprint_source,
    verify_archive,
)


def git(repository: Path, *args: str) -> str:
    return (
        subprocess.run(
            ["git", "-c", "protocol.file.allow=always", "-C", str(repository), *args],
            capture_output=True,
            check=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        .stdout.decode()
        .strip()
    )


def repository(path: Path) -> Path:
    path.mkdir()
    git(path, "init")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "core.hooksPath", ".git/hooks")
    (path / "main.py").write_text("print('original')\n")
    git(path, "add", ".")
    git(path, "commit", "-m", "initial")
    return path


def project(root: Path, repo: Path, name: str = "demo") -> SimpleNamespace:
    folder = root / "projects" / name
    folder.mkdir(parents=True)
    return SimpleNamespace(
        id=name,
        repository=repo,
        archive=folder / f"{name}.git",
        metadata={},
        directory=folder,
        store=SimpleNamespace(root=root),
    )


def saved_run(item: SimpleNamespace, run_id: str, snapshot: dict) -> SimpleNamespace:
    return SimpleNamespace(project=item, id=run_id, metadata={"git": snapshot})


def test_dirty_snapshot_preserves_real_index_and_restores_without_original(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "repo")
    item = project(tmp_path / "store", repo)
    original_head = git(repo, "rev-parse", "HEAD")
    (repo / "main.py").write_text("print('staged')\n")
    git(repo, "add", "main.py")
    (repo / "main.py").write_text("print('actual worktree')\n")
    (repo / "extensionless-source").write_text("all source names are captured\n")
    (repo / "data").mkdir()
    (repo / "data/generated.bin").write_bytes(b"not source")
    (repo / "outputs").mkdir()
    (repo / "outputs/result.py").write_text("not source either")
    index = (repo / ".git/index").read_bytes()
    boundary = fingerprint_source(item)

    snapshot = archive_snapshot(item, "run-1")

    assert snapshot["commit"] != original_head
    assert fingerprint_source(item) == boundary
    assert (repo / ".git/index").read_bytes() == index
    assert git(repo, "rev-parse", "HEAD") == original_head
    assert archive_snapshot(item, "run-1") == snapshot
    assert git(item.archive, "rev-parse", "refs/runs/run-1") == snapshot["commit"]
    shutil.rmtree(repo)
    restored = checkout_source(
        saved_run(item, "run-1", snapshot), tmp_path / "restored"
    )
    assert (restored / "main.py").read_text() == "print('actual worktree')\n"
    assert (restored / "extensionless-source").is_file()
    assert not (restored / "data").exists()
    assert not (restored / "outputs").exists()
    assert not (item.archive / "objects/info/alternates").exists()
    assert verify_archive(item, offline=True)["offline_checked"] == 1


def test_dirty_recursive_submodule_gitlinks_and_copied_archive_are_independent(
    tmp_path: Path,
) -> None:
    dep = repository(tmp_path / "dependency")
    repo = repository(tmp_path / "repo")
    git(repo, "submodule", "add", str(dep), "libs/dependency")
    git(repo, "commit", "-am", "add dependency")
    child = repo / "libs/dependency"
    (child / "main.py").write_text("dirty submodule\n")
    (child / "new-config").write_text("new child source\n")
    item = project(tmp_path / "store", repo)
    snapshot = archive_snapshot(item, "submodule-run")
    [module] = snapshot["submodules"]
    parent_link = git(item.archive, "ls-tree", snapshot["commit"], "libs/dependency")
    assert module["commit"] in parent_link
    assert module["commit"] != git(child, "rev-parse", "HEAD")

    target = project(tmp_path / "other-store", repo)
    copy_archive(item, target)
    shutil.rmtree(repo)
    shutil.rmtree(dep)
    shutil.rmtree(item.store.root)

    restored = checkout_source(
        saved_run(target, "submodule-run", snapshot), tmp_path / "restored"
    )
    assert (restored / "libs/dependency/main.py").read_text() == "dirty submodule\n"
    assert (restored / "libs/dependency/new-config").is_file()
    assert verify_archive(target, offline=True)["offline_checked"] == 1


def test_new_source_bytes_change_fingerprint_and_cannot_move_retained_ref(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "repo")
    item = project(tmp_path / "store", repo)
    before = fingerprint_source(item)
    archive_snapshot(item, "fixed")
    (repo / "main.py").write_text("changed\n")
    assert fingerprint_source(item) != before
    with pytest.raises(ConflictError, match="immutable source ref"):
        archive_snapshot(item, "fixed")


def test_lfs_history_and_dirty_worktree_restore_with_old_endpoint_unavailable(
    tmp_path: Path,
) -> None:
    if subprocess.run(
        ["git", "lfs", "version"], capture_output=True, check=False
    ).returncode:
        pytest.skip("git-lfs is not installed")
    repo = repository(tmp_path / "repo")
    git(repo, "lfs", "install", "--local", "--skip-smudge", "--force")
    git(repo, "lfs", "track", "*.bin")
    old = b"old LFS payload\n" * 4000
    new = b"dirty LFS payload\n" * 5000
    (repo / "source.bin").write_bytes(old)
    (repo / ".lfsconfig").write_text(
        '[lfs]\n  url = "https://unreachable.invalid/old-lfs"\n'
    )
    git(repo, "add", ".gitattributes", ".lfsconfig", "source.bin")
    git(repo, "commit", "-m", "LFS history")
    item = project(tmp_path / "store", repo)
    archive_snapshot(item, "old")
    (repo / "source.bin").write_bytes(new)
    snapshot = archive_snapshot(item, "new")
    for payload in (old, new):
        digest = hashlib.sha256(payload).hexdigest()
        archived = item.archive / "lfs/objects" / digest[:2] / digest[2:4] / digest
        cached = repo / ".git/lfs/objects" / digest[:2] / digest[2:4] / digest
        assert archived.read_bytes() == payload
        assert archived.stat().st_ino != cached.stat().st_ino
    target = project(tmp_path / "target-store", repo)
    copy_archive(item, target)
    shutil.rmtree(repo)
    shutil.rmtree(item.store.root)
    restored = checkout_source(
        saved_run(target, "new", snapshot), tmp_path / "restored"
    )
    assert (restored / "source.bin").read_bytes() == new
    assert git(restored, "config", "--get", "lfs.url").startswith("file://")
    result = verify_archive(target, offline=True)
    assert result["offline_checked"] == 2
    assert result["lfs_objects"] == 2


def test_archive_rejects_alternates_and_corrupt_lfs(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    item = project(tmp_path / "store", repo)
    archive_snapshot(item, "one")
    alternate = item.archive / "objects/info/alternates"
    alternate.write_text(str(repo / ".git/objects") + "\n")
    with pytest.raises(IntegrityError, match="external or shallow"):
        verify_archive(item)


def test_shallow_source_is_rejected_before_publishing_run_ref(tmp_path: Path) -> None:
    origin = repository(tmp_path / "origin")
    (origin / "main.py").write_text("second commit\n")
    git(origin, "commit", "-am", "second")
    git(tmp_path, "clone", "--depth=1", origin.as_uri(), str(tmp_path / "shallow"))
    item = project(tmp_path / "store", tmp_path / "shallow")
    with pytest.raises(IntegrityError, match="shallow source"):
        archive_snapshot(item, "shallow-run")
    assert not item.archive.exists() or not git(
        item.archive, "for-each-ref", "refs/runs/"
    )


def test_tracked_source_is_preserved_under_default_generated_directory_names(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "repo")
    (repo / "data").mkdir()
    (repo / "data/schema.py").write_text("original tracked source\n")
    git(repo, "add", "data/schema.py")
    git(repo, "commit", "-m", "tracked dependency")
    (repo / "data/schema.py").write_text("dirty tracked source\n")
    (repo / "data/untracked.bin").write_bytes(b"generated")
    item = project(tmp_path / "store", repo)
    snapshot = archive_snapshot(item, "tracked")
    restored = checkout_source(
        saved_run(item, "tracked", snapshot), tmp_path / "restored"
    )
    assert (restored / "data/schema.py").read_text() == "dirty tracked source\n"
    assert not (restored / "data/untracked.bin").exists()


def test_deleted_submodule_is_saved_as_deletion(tmp_path: Path) -> None:
    child = repository(tmp_path / "child")
    parent = repository(tmp_path / "parent")
    git(parent, "submodule", "add", str(child), "libs/child")
    git(parent, "commit", "-am", "add submodule")
    git(parent, "rm", "-f", "libs/child")
    item = project(tmp_path / "store", parent)
    fingerprint_source(item)
    snapshot = archive_snapshot(item, "deleted")
    restored = checkout_source(
        saved_run(item, "deleted", snapshot), tmp_path / "restored"
    )
    assert not (restored / "libs/child").exists()
    assert snapshot["submodules"] == []


def test_unregistered_nested_repository_cannot_publish_a_dangling_gitlink(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "repo")
    repository(repo / "embedded")
    item = project(tmp_path / "store", repo)
    with pytest.raises(IntegrityError, match="unregistered nested"):
        archive_snapshot(item, "nested")
    assert not git(item.archive, "for-each-ref", "refs/runs/")


def test_explicit_external_dependency_changes_boundary_and_restores_offline(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "repo")
    dependency = repository(tmp_path / "physics")
    item = project(tmp_path / "store", repo)
    item.settings = {"source": {"dependencies": {"physics": "../physics"}}}
    before = fingerprint_source(item)
    (dependency / "main.py").write_text("actual external source\n")
    assert fingerprint_source(item) != before
    snapshot = archive_snapshot(item, "external")
    assert snapshot["dependencies"][0]["path"] == "external/physics"
    shutil.rmtree(repo)
    shutil.rmtree(dependency)
    restored = checkout_source(
        saved_run(item, "external", snapshot), tmp_path / "restored"
    )
    assert (
        restored / "external/physics/main.py"
    ).read_text() == "actual external source\n"
    assert verify_archive(item, offline=True)["offline_checked"] == 1

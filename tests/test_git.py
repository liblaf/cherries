# Copyright (c) 2026 liblaf
"""Native snapshot isolation and archive closure checks."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from liblaf.cherries import _git


def git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "-C", str(repo), *args],
        input=data,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
    ).stdout


def init(path: Path, *, bare: bool = False) -> Path:
    path.mkdir(parents=True)
    git(path, "init", *(["--bare"] if bare else []))
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    return path


def commit(repo: Path, message: str = "source") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").decode().strip()


def test_snapshot_preserves_index_and_selects_current_source(tmp_path: Path) -> None:
    repo = init(tmp_path / "repo")
    (repo / "source.py").write_text("original\n")
    (repo / ".gitignore").write_text(
        "ignored.py\ncherries/\nexp/**/data/\nexp/**/figs/\n"
    )
    study = repo / "exp/2026/11/15/test"
    (study / "data").mkdir(parents=True)
    (study / "data/tracked.dat").write_text("excluded even when tracked\n")
    (study / "tmp").mkdir()
    (study / "tmp/debug.bin").write_bytes(b"debug intermediates")
    git(repo, "add", "-f", "exp/2026/11/15/test/data/tracked.dat")
    git(repo, "add", "-f", "exp/2026/11/15/test/tmp/debug.bin")
    head = commit(repo)
    (repo / "source.py").write_text("staged\n")
    git(repo, "add", "source.py")
    (repo / "source.py").write_text("ending\n")
    (repo / "ignored.py").write_text("staged ignored\n")
    git(repo, "add", "-f", "ignored.py")
    (repo / "new.py").write_text("new source\n")
    (repo / "cherries").mkdir()
    (repo / "cherries/record").write_text("excluded\n")
    (study / "figs").mkdir()
    (study / "figs/plot.png").write_bytes(b"excluded")
    index = (repo / ".git/index").read_bytes()
    saved = _git.snapshot(repo, "run-one")
    assert (repo / ".git/index").read_bytes() == index
    assert git(repo, "rev-parse", "HEAD").decode().strip() == head
    assert (repo / "source.py").read_text() == "ending\n"
    assert git(repo, "show", f"{saved}:source.py") == b"ending\n"
    assert git(repo, "show", f"{saved}:ignored.py") == b"staged ignored\n"
    assert git(repo, "show", f"{saved}:new.py") == b"new source\n"
    files = git(repo, "ls-tree", "-r", "--name-only", saved).decode().splitlines()
    assert not any(
        "data/" in p or "figs/" in p or "tmp/" in p or p.startswith("cherries/")
        for p in files
    )
    assert git(repo, "rev-parse", f"{saved}^").decode().strip() == head
    _git.verify(repo, "run-one", saved)


def test_empty_repository_snapshot(tmp_path: Path) -> None:
    repo = init(tmp_path / "repo")
    (repo / "new.py").write_text("pass\n")
    saved = _git.snapshot(repo, "first")
    assert git(repo, "show", f"{saved}:new.py") == b"pass\n"
    assert not (repo / ".git/index").exists()
    _git.verify(repo, "first", saved)


def test_dirty_recursive_submodule_and_lfs_round_trip(tmp_path: Path) -> None:  # noqa: PLR0915
    if subprocess.run(
        ["git", "lfs", "version"], capture_output=True, check=False
    ).returncode:
        pytest.skip("Git LFS is unavailable")
    leaf = init(tmp_path / "leaf")
    git(leaf, "lfs", "install", "--local")
    (leaf / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
    (leaf / "weights.bin").write_bytes(b"initial payload\0" * 100)
    leaf_head = commit(leaf)
    child = init(tmp_path / "child")
    (child / "child.py").write_text("original\n")
    commit(child)
    git(child, "submodule", "add", str(leaf), "nested/leaf")
    commit(child)
    repo = init(tmp_path / "repo")
    (repo / "main.py").write_text("pass\n")
    commit(repo)
    git(
        repo,
        "submodule",
        "add",
        "--name",
        "custom-child-name",
        str(child),
        "deps/child",
    )
    commit(repo)
    git(repo, "submodule", "update", "--init", "--recursive")
    working_child = repo / "deps/child"
    working_leaf = working_child / "nested/leaf"
    (working_child / "child.py").write_text("dirty child\n")
    git(working_leaf, "lfs", "install", "--local")
    payload = b"ending LFS payload\0" * 300
    (working_leaf / "weights.bin").write_bytes(payload)
    saved = _git.snapshot(repo, "round-trip")
    child_saved = (
        git(working_child, "rev-parse", "refs/cherries/runs/round-trip")
        .decode()
        .strip()
    )
    leaf_saved = (
        git(working_leaf, "rev-parse", "refs/cherries/runs/round-trip").decode().strip()
    )
    assert git(working_child, "show", f"{child_saved}:child.py") == b"dirty child\n"
    assert git(working_leaf, "rev-parse", "HEAD").decode().strip() == leaf_head
    archive = tmp_path / "archive.git"
    _git.transfer(repo, archive, "round-trip")
    _git.verify(archive, "round-trip", saved)
    archive_child = archive / "modules/deps/child"
    archive_leaf = archive_child / "modules/nested/leaf"
    assert (
        git(archive_child, "rev-parse", "refs/cherries/runs/round-trip")
        .decode()
        .strip()
        == child_saved
    )
    assert (
        git(archive_leaf, "rev-parse", "refs/cherries/runs/round-trip").decode().strip()
        == leaf_saved
    )
    digest = hashlib.sha256(payload).hexdigest()
    archived_payload = archive_leaf / f"lfs/objects/{digest[:2]}/{digest[2:4]}/{digest}"
    assert archived_payload.read_bytes() == payload
    archived_payload.write_bytes(b"X" + payload[1:])
    with pytest.raises(RuntimeError, match="Corrupt LFS"):
        _git.verify(archive, "round-trip", saved)
    archived_payload.write_bytes(payload)
    restored = init(tmp_path / "restored")
    (restored / "local.py").write_text("preserve\n")
    local_head = commit(restored)
    local_index = (restored / ".git/index").read_bytes()
    _git.transfer(archive, restored, "round-trip")
    _git.verify(restored, "round-trip", saved)
    assert git(restored, "rev-parse", "HEAD").decode().strip() == local_head
    assert (restored / ".git/index").read_bytes() == local_index
    assert not (restored / "deps").exists()
    _git.remove(restored, "round-trip")
    assert not git(restored, "for-each-ref", "refs/cherries/runs/").strip()
    assert not git(
        restored / ".git/modules/deps/child", "for-each-ref", "refs/cherries/runs/"
    ).strip()


def test_historical_gitlinks_survive_transfer_and_gc(tmp_path: Path) -> None:
    child = init(tmp_path / "child")
    (child / "historical.py").write_text("historical child\n")
    historical = commit(child)
    repo = init(tmp_path / "repo")
    (repo / "main.py").write_text("pass\n")
    commit(repo)
    git(repo, "submodule", "add", "--name", "old-name", str(child), "old/path")
    commit(repo)
    git(repo, "rm", "-f", "old/path")
    commit(repo)
    saved = _git.snapshot(repo, "history")
    archive = tmp_path / "archive.git"
    _git.transfer(repo, archive, "history")
    archived_child = archive / "modules/old/path"
    # The child is reachable exclusively through a historical parent gitlink.
    assert not git(archived_child, "for-each-ref").strip()
    dangling = (
        git(
            archived_child, "hash-object", "-w", "--stdin", data=b"unused source blob\n"
        )
        .decode()
        .strip()
    )
    before = sorted(p.relative_to(archive) for p in archive.rglob("*") if p.is_file())
    plan = _git.gc(archive, dry_run=True)
    assert plan["objects"] >= 1
    assert before == sorted(
        p.relative_to(archive) for p in archive.rglob("*") if p.is_file()
    )
    reclaimed = _git.gc(archive)
    assert reclaimed == plan
    assert (
        git(archived_child, "show", f"{historical}:historical.py")
        == b"historical child\n"
    )
    assert subprocess.run(
        ["git", "-C", str(archived_child), "cat-file", "-e", dangling],
        capture_output=True,
        check=False,
    ).returncode
    _git.verify(archive, "history", saved)


def test_gc_preserves_reflog_lfs_and_collects_unreferenced_payload(
    tmp_path: Path,
) -> None:
    repo = init(tmp_path / "repo")
    git(repo, "lfs", "install", "--local")
    (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
    (repo / "weights.bin").write_bytes(b"first payload")
    first = commit(repo)
    second_payload = b"reachable through reflog only"
    (repo / "weights.bin").write_bytes(second_payload)
    second = commit(repo)
    git(repo, "reset", "--hard", first)
    saved = _git.snapshot(repo, "reflog")
    before = (repo / ".git/logs/HEAD").read_bytes()
    digest = hashlib.sha256(second_payload).hexdigest()
    retained = repo / f".git/lfs/objects/{digest[:2]}/{digest[2:4]}/{digest}"
    orphan_digest = hashlib.sha256(b"orphan").hexdigest()
    orphan = (
        repo
        / f".git/lfs/objects/{orphan_digest[:2]}/{orphan_digest[2:4]}/{orphan_digest}"
    )
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    assert _git.gc(repo, dry_run=True) == {"objects": 1, "bytes": 6}
    assert _git.gc(repo) == {"objects": 1, "bytes": 6}
    assert not orphan.exists()
    assert retained.read_bytes() == second_payload
    assert git(repo, "cat-file", "-t", second) == b"commit\n"
    assert (repo / ".git/logs/HEAD").read_bytes() == before
    _git.verify(repo, "reflog", saved)

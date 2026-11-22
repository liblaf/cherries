# Copyright (c) 2026 liblaf
"""Non-invasive HEAD + diff.patch capture, dirty LFS rejection, and submodule checks."""

from __future__ import annotations

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


def init(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    return path


def commit(repo: Path, message: str = "source") -> str:
    git(repo, "add", "-A")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        message,
    )
    return git(repo, "rev-parse", "HEAD").decode().strip()


def test_capture_preserves_index_and_produces_applicable_diff_patch(
    tmp_path: Path,
) -> None:
    repo = init(tmp_path / "repo")
    (repo / "source.py").write_text("original\n")
    (repo / "removed.py").write_text("remove me\n")
    (repo / ".gitignore").write_text(
        "ignored.py\ncherries/\nexp/**/data/\nexp/**/figs/\nexp/**/tmp/\n"
    )
    study = repo / "exp/2026/11/15/test"
    (study / "data").mkdir(parents=True)
    (study / "data/tracked.dat").write_text("tracked data\n")
    (study / "tmp").mkdir()
    (study / "tmp/debug.bin").write_bytes(b"tracked debug")
    git(repo, "add", "-f", "exp/2026/11/15/test/data/tracked.dat")
    git(repo, "add", "-f", "exp/2026/11/15/test/tmp/debug.bin")
    head = commit(repo)

    (repo / "source.py").write_text("staged\n")
    git(repo, "add", "source.py")
    (repo / "source.py").write_text("ending\n")
    (repo / "removed.py").unlink()
    (repo / "ignored.py").write_text("staged ignored\n")
    git(repo, "add", "-f", "ignored.py")
    (repo / "new.py").write_text("new source\n")
    (repo / "small.bin").write_bytes(b"\x00\x01\xffbinary")
    (repo / "cherries").mkdir()
    (repo / "cherries/record").write_text("excluded\n")
    (study / "data/tracked.dat").write_text("mutated tracked data\n")
    (study / "tmp/debug.bin").write_bytes(b"mutated tracked debug")
    (study / "figs").mkdir()
    (study / "figs/plot.png").write_bytes(b"excluded")

    index = (repo / ".git/index").read_bytes()
    recorded_head, patch = _git.capture(repo)

    assert recorded_head == head
    assert (repo / ".git/index").read_bytes() == index
    assert git(repo, "rev-parse", "HEAD").decode().strip() == head
    assert not git(repo, "for-each-ref", "refs/cherries/").strip()
    assert patch
    patch_text = patch.decode("utf-8", errors="replace")
    assert "cherries/" not in patch_text
    assert "data/tracked.dat" not in patch_text
    assert "tmp/debug.bin" not in patch_text
    assert "figs/plot.png" not in patch_text

    # Reproducing on a clean clone of HEAD with git apply restores exact ending source.
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(repo), str(clone))
    git(clone, "checkout", recorded_head)
    git(clone, "apply", "--index", data=patch)
    assert (clone / "source.py").read_text() == "ending\n"
    assert not (clone / "removed.py").exists()
    assert (clone / "ignored.py").read_text() == "staged ignored\n"
    assert (clone / "new.py").read_text() == "new source\n"
    assert (clone / "small.bin").read_bytes() == b"\x00\x01\xffbinary"
    # Excluded tracked files stay untouched at HEAD instead of being deleted.
    assert (clone / "exp/2026/11/15/test/data/tracked.dat").read_text() == (
        "tracked data\n"
    )


def test_clean_repo_produces_empty_patch(tmp_path: Path) -> None:
    repo = init(tmp_path / "repo")
    (repo / "main.py").write_text("pass\n")
    head = commit(repo)
    recorded_head, patch = _git.capture(repo)
    assert recorded_head == head
    assert patch == b""


def test_unborn_head_is_rejected(tmp_path: Path) -> None:
    repo = init(tmp_path / "repo")
    (repo / "new.py").write_text("pass\n")
    with pytest.raises(RuntimeError, match="no HEAD commit"):
        _git.capture(repo)


def test_clean_lfs_is_allowed_and_dirty_lfs_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = init(tmp_path / "repo")
    if (
        subprocess.run(
            ["git", "lfs", "version"], capture_output=True, check=False
        ).returncode
        == 0
    ):
        git(repo, "lfs", "install", "--local")
    (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
    (repo / "weights.bin").write_bytes(b"committed lfs bytes")
    (repo / "main.py").write_text("v1\n")
    head = commit(repo)

    # Clean committed LFS with a dirty ordinary Python file succeeds.
    (repo / "main.py").write_text("v2\n")
    recorded_head, patch = _git.capture(repo)
    assert recorded_head == head
    assert b"main.py" in patch
    assert b"weights.bin" not in patch

    # Excluded study data matching *.bin is not treated as dirty LFS.
    data_file = repo / "exp/2026/11/15/study/data/mesh.bin"
    data_file.parent.mkdir(parents=True)
    data_file.write_bytes(b"study data")
    recorded_head, _ = _git.capture(repo)
    assert recorded_head == head

    # Untracked LFS file outside excluded roots fails fast.
    (repo / "untracked.bin").write_bytes(b"new lfs")
    with pytest.raises(RuntimeError, match=r"Dirty Git LFS.*untracked\.bin"):
        _git.capture(repo)
    (repo / "untracked.bin").unlink()

    # Modified tracked LFS file fails fast.
    (repo / "weights.bin").write_bytes(b"modified lfs bytes")
    with pytest.raises(RuntimeError, match=r"Dirty Git LFS.*weights\.bin"):
        _git.capture(repo)


def test_clean_submodule_is_allowed_and_dirty_submodule_is_rejected(
    tmp_path: Path,
) -> None:
    child = init(tmp_path / "child")
    (child / "lib.py").write_text("v1\n")
    commit(child)

    repo = init(tmp_path / "repo")
    (repo / "main.py").write_text("pass\n")
    commit(repo)
    git(repo, "submodule", "add", str(child), "deps/child")
    head = commit(repo)

    # Clean submodule succeeds with empty patch.
    recorded_head, patch = _git.capture(repo)
    assert recorded_head == head
    assert patch == b""

    # Cleanly moving the submodule to a new commit records the gitlink bump.
    working_child = repo / "deps/child"
    (working_child / "lib.py").write_text("v2\n")
    new_child_head = commit(working_child, "v2")
    recorded_head, patch = _git.capture(repo)
    assert recorded_head == head
    assert new_child_head.encode() in patch

    # Any dirty modification or untracked file inside the submodule fails fast.
    (working_child / "lib.py").write_text("dirty\n")
    with pytest.raises(RuntimeError, match=r"Dirty submodule.*deps/child"):
        _git.capture(repo)
    git(working_child, "checkout", "--", "lib.py")
    (working_child / "untracked.py").write_text("untracked\n")
    with pytest.raises(RuntimeError, match=r"Dirty submodule.*deps/child"):
        _git.capture(repo)


def test_replacing_tracked_file_with_directory_produces_valid_patch(
    tmp_path: Path,
) -> None:
    repo = init(tmp_path / "repo")
    (repo / "module").write_text("old file\n")
    head = commit(repo)

    (repo / "module").unlink()
    (repo / "module").mkdir()
    (repo / "module/new.py").write_text("new package\n")

    recorded_head, patch = _git.capture(repo)
    assert recorded_head == head

    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(repo), str(clone))
    git(clone, "checkout", recorded_head)
    git(clone, "apply", "--index", data=patch)
    assert (clone / "module/new.py").read_text() == "new package\n"


def test_symlink_to_git_repo_and_custom_diff_config_produce_standard_patch(
    tmp_path: Path,
) -> None:
    other = init(tmp_path / "other")
    (other / "dirty.py").write_text("untracked\n")

    repo = init(tmp_path / "repo")
    (repo / "main.py").write_text("v1\n")
    head = commit(repo)
    git(repo, "config", "diff.noprefix", "true")
    git(repo, "config", "diff.mnemonicPrefix", "true")

    (repo / "main.py").write_text("v2\n")
    (repo / "link_to_other").symlink_to(other)

    recorded_head, patch = _git.capture(repo)
    assert recorded_head == head
    assert b"diff --git a/main.py b/main.py" in patch

    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(repo), str(clone))
    git(clone, "checkout", recorded_head)
    git(clone, "apply", "--index", data=patch)
    assert (clone / "main.py").read_text() == "v2\n"
    assert (clone / "link_to_other").is_symlink()

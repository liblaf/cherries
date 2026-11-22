# Copyright (c) 2026 liblaf
# ruff: noqa: EM102, TRY003
"""Non-invasive HEAD commit and diff.patch capture, rejecting dirty LFS/submodules."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path


def _git(
    repo: Path,
    *args: str,
    data: bytes | None = None,
    env: dict[str, str] | None = None,
    required: bool = True,
) -> bytes:
    result = subprocess.run(
        [
            "git",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-C",
            str(repo),
            *args,
        ],
        input=data,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", **(env or {})},
    )
    if result.returncode and required:
        raise RuntimeError(
            f"Git {' '.join(args[:2])} in {repo}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout if result.returncode == 0 else b""


def _excluded(name: str) -> bool:
    parts = Path(name).parts
    return bool(
        parts
        and (
            parts[0] == "cherries"
            or (
                parts[0] == "exp"
                and any(part in {"data", "figs", "tmp"} for part in parts[1:])
            )
        )
    )


def _reject_dirty_lfs(repo: Path, paths: Sequence[str]) -> None:
    if not paths:
        return
    output = _git(
        repo,
        "check-attr",
        "-z",
        "--stdin",
        "filter",
        data=b"\0".join(os.fsencode(path) for path in paths) + b"\0",
    )
    tokens = output.split(b"\0")
    dirty = [
        os.fsdecode(tokens[index])
        for index in range(0, len(tokens) - 2, 3)
        if tokens[index + 2] == b"lfs"
    ]
    if dirty:
        raise RuntimeError(
            "Dirty Git LFS files are not supported: " + ", ".join(sorted(dirty))
        )


def root(path: Path) -> Path:
    """Return the enclosing Git repository root for path."""
    return Path(
        os.fsdecode(_git(path, "rev-parse", "--show-toplevel").strip())
    ).resolve()


def _clean_submodule_head(path: Path, name: str) -> str:
    if _git(path, "status", "--porcelain=v1", "--ignore-submodules=none"):
        raise RuntimeError(f"Dirty submodule is not supported: {name}")
    return _git(path, "rev-parse", "--verify", "HEAD", required=False).decode().strip()


def _inspect(repo: Path) -> tuple[str, list[str], list[str], dict[str, str]]:
    head = _git(repo, "rev-parse", "--verify", "HEAD", required=False).decode().strip()
    if not head:
        raise RuntimeError(f"Git repository has no HEAD commit: {repo}")
    status = _git(
        repo,
        "status",
        "--porcelain=v1",
        "-z",
        "-uall",
        "--no-renames",
        "--ignore-submodules=none",
    )
    present: list[str] = []
    removed: list[str] = []
    submodules: dict[str, str] = {}
    for entry in status.split(b"\0"):
        if len(entry) <= 3:
            continue
        code = entry[:2]
        name = os.fsdecode(entry[3:]).rstrip("/")
        if _excluded(name):
            continue
        path = repo / name
        if path.is_symlink() or path.is_file():
            present.append(name)
        elif (path / ".git").exists():
            if sub_head := _clean_submodule_head(path, name):
                submodules[name] = sub_head
        elif not path.exists() or b"D" in code:
            removed.append(name)
        elif path.is_dir() and any(path.iterdir()):
            raise RuntimeError(f"Dirty submodule is not supported: {name}")
    present = sorted(set(present))
    removed = sorted(set(removed) - set(present))
    _reject_dirty_lfs(repo, present)
    return head, present, removed, submodules


def preflight(repo: Path) -> None:
    """Fail fast before running if HEAD is missing or LFS/submodules are dirty."""
    _inspect(repo.resolve())


def capture(repo: Path) -> tuple[str, bytes]:
    """Return HEAD OID and a binary diff against HEAD without touching Git state."""
    repo = repo.resolve()
    head, present, removed, submodules = _inspect(repo)
    if not present and not removed and not submodules:
        return head, b""
    with tempfile.TemporaryDirectory(prefix="cherries-index-") as folder:
        env = {
            "GIT_INDEX_FILE": str(Path(folder) / "index"),
            "GIT_LITERAL_PATHSPECS": "1",
        }
        _git(repo, "read-tree", head, env=env)
        for name, oid in submodules.items():
            _git(
                repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{oid},{name}",
                env=env,
            )
        if removed:
            _git(
                repo,
                "update-index",
                "--force-remove",
                "-z",
                "--stdin",
                env=env,
                data=b"\0".join(os.fsencode(path) for path in removed) + b"\0",
            )
        if present:
            _git(
                repo,
                "add",
                "--force",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                env=env,
                data=b"\0".join(os.fsencode(path) for path in present) + b"\0",
            )
        patch = _git(
            repo,
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-relative",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            head,
            env=env,
        )
    return head, patch

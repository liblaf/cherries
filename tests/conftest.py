# Copyright (c) 2026 liblaf
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    path = tmp_path / "experiment"
    path.mkdir()
    git(path, "init")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    (path / ".gitignore").write_text(
        "cherries/\nexp/**/data/\nexp/**/figs/\nexp/**/tmp/\n"
    )
    git(path, "add", ".gitignore")
    git(path, "commit", "-m", "initial source")
    return path


def execute(
    repo: Path, body: str, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    entry = repo / "exp/2026/11/15/example/src/10-run.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(body)
    source = Path(__file__).resolve().parents[1] / "src"
    return subprocess.run(
        [sys.executable, str(entry)],
        cwd=repo.parent,
        capture_output=True,
        text=True,
        check=check,
        env={**os.environ, "PYTHONPATH": str(source), "PYTHON_COLORS": "0"},
    )


@pytest.fixture
def saved(repo: Path) -> Path:
    execute(
        repo,
        """from liblaf import cherries
def main():
    cherries.output("result.txt").write_text("shared contents")
    cherries.output("other.lfs").write_text("shared contents")
    cherries.output("empty.bin").write_bytes(b"")
    tree = cherries.output("bundle")
    (tree / "nested/empty").mkdir(parents=True)
    (tree / "nested/data.bin").write_bytes(b"tree data")
    cherries.fig("loss.png").write_bytes(b"figure")
if __name__ == "__main__":
    cherries.run(main, name="record", description="initial", tags=["baseline"])
""",
    )
    return next((repo / "cherries/runs").glob("*/*/*/*/run.yaml")).parent

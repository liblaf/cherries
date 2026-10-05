# Copyright (c) 2026 liblaf
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from liblaf import cherries
from liblaf.cherries import _capture, core
from liblaf.cherries.core.plugin import PluginManager
from liblaf.cherries.profiles import Profile
from liblaf.cherries.records import Store


def git(directory: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(directory), *args],
        check=True,
        capture_output=True,
    )


def git_repo(tmp_path: Path, name: str = "project") -> Path:
    project = tmp_path / name
    project.mkdir()
    git(project, "init")
    git(project, "config", "user.email", "test@example.com")
    git(project, "config", "user.name", "Test User")
    return project


def commit_all(project: Path, message: str = "initial") -> None:
    git(project, "add", "--all")
    git(project, "commit", "-m", message)


def capture(
    project: Path,
    entrypoint: Path,
    target: Path,
    monkeypatch: pytest.MonkeyPatch,
    **settings,
) -> dict[str, Any]:
    monkeypatch.setattr(_capture, "_editable_roots", list)
    return _capture.capture_source(project, entrypoint, target, settings)


def test_capture_records_staged_and_unstaged_binary_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = git_repo(tmp_path)
    entrypoint = project / "run.py"
    entrypoint.write_text("print('base')\n")
    binary = project / "state.bin"
    binary.write_bytes(b"\x00base\xff")
    commit_all(project)

    binary.write_bytes(b"\x00staged\xfe")
    git(project, "add", "state.bin")
    entrypoint.write_text("print('unstaged')\n")

    evidence = capture(project, entrypoint, tmp_path / "capture", monkeypatch)

    root = next(item for item in evidence["repositories"] if item["path"] == ".")
    patch = (tmp_path / "capture/git/project/working-tree.patch").read_bytes()
    assert b"GIT binary patch" in patch
    assert b"state.bin" in patch
    assert b"run.py" in patch
    assert root["patch_sha256"]
    assert b"M  state.bin" in (tmp_path / "capture/git/project/status").read_bytes()
    assert b" M run.py" in (tmp_path / "capture/git/project/status").read_bytes()


def test_capture_preserves_an_unborn_repository_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = git_repo(tmp_path)
    entrypoint = project / "run.py"
    entrypoint.write_text("print('staged')\n")
    git(project, "add", "run.py")
    entrypoint.write_text("print('unstaged')\n")

    evidence = capture(project, entrypoint, tmp_path / "capture", monkeypatch)

    root = next(item for item in evidence["repositories"] if item["path"] == ".")
    patch = (tmp_path / "capture/git/project/working-tree.patch").read_bytes()
    assert root["head"] is None
    assert b"new file mode 100644" in patch
    assert b"print('staged')" in patch
    assert b"print('unstaged')" in patch


def test_capture_records_dirty_submodule_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = git_repo(tmp_path, "library")
    (child / "library.py").write_text("VERSION = 'base'\n")
    commit_all(child)
    project = git_repo(tmp_path, "project")
    (project / "run.py").write_text("print('run')\n")
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(child),
            "libs/library",
        ],
        check=True,
        capture_output=True,
    )
    commit_all(project)
    (project / "libs/library/library.py").write_text("VERSION = 'dirty'\n")

    evidence = capture(project, project / "run.py", tmp_path / "capture", monkeypatch)

    entries = {item["path"]: item for item in evidence["repositories"]}
    assert set(entries) == {".", "libs/library"}
    assert entries["libs/library"]["patch_sha256"] != ""
    assert (
        b"library.py"
        in (tmp_path / "capture/git/libs/library/working-tree.patch").read_bytes()
    )
    assert "libs/library" in entries["."]["submodules"]


def test_capture_keeps_explicit_ignored_build_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = git_repo(tmp_path)
    entrypoint = project / "run.py"
    entrypoint.write_text("print('run')\n")
    (project / ".gitignore").write_text("generated/\n")
    generated = project / "generated" / "build.py"
    generated.parent.mkdir()
    generated.write_text("VALUE = 42\n")
    commit_all(project)

    evidence = capture(
        project,
        entrypoint,
        tmp_path / "capture",
        monkeypatch,
        capture={"files": ["generated/build.py"]},
    )

    assert evidence["selected"] == [
        {
            "path": "generated/build.py",
            "sha256": hashlib.sha256(generated.read_bytes()).hexdigest(),
        }
    ]
    assert (
        tmp_path / "capture/selected/generated/build.py"
    ).read_text() == "VALUE = 42\n"


def test_capture_does_not_follow_untracked_symlink_outside_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = git_repo(tmp_path)
    entrypoint = project / "run.py"
    entrypoint.write_text("print('run')\n")
    commit_all(project)
    private = tmp_path / "outside.py"
    private.write_text("PRIVATE = 'do not capture'\n")
    (project / "linked.py").symlink_to(private)

    evidence = capture(project, entrypoint, tmp_path / "capture", monkeypatch)

    root = next(item for item in evidence["repositories"] if item["path"] == ".")
    assert root["untracked"] == []
    assert not (tmp_path / "capture/git/project/untracked/linked.py").exists()


def make_replay_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Store, str, Path]:
    project = git_repo(tmp_path)
    entrypoint = project / "run.py"
    entrypoint.write_text("print('replay')\n")
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'example'\nversion = '0'\n"
    )
    commit_all(project)
    store = Store(tmp_path / "store", machine_id="test-machine")
    run_id = "replay-record"
    work = store.start_work(run_id)
    evidence = capture(project, entrypoint, work / "source", monkeypatch)
    (work / "inputs").mkdir()
    (work / "inputs" / "mesh.txt").write_text("mesh\n")
    (work / "environment").mkdir()
    (work / "environment" / "pyproject.toml").write_text(
        (project / "pyproject.toml").read_text()
    )
    store.seal(
        run_id,
        {
            "kind": "experiment",
            "entrypoint": "run.py",
            "source": evidence,
            "source_stability": True,
            "argv": ["--steps", "5"],
            "input_bindings": [
                {"source": "data/mesh.txt", "staged_path": "inputs/mesh.txt"}
            ],
        },
        work,
    )
    return store, run_id, project


def test_replay_reconstructs_entrypoint_and_input_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run_id, _ = make_replay_record(tmp_path, monkeypatch)

    prepared = _capture.prepare_replay(store, run_id, tmp_path / "replay")

    assert Path(prepared["entrypoint"]).read_text() == "print('replay')\n"
    assert json.loads(Path(prepared["input_mapping"]).read_text()) == {
        "data/mesh.txt": f"run:{run_id}/inputs/mesh.txt"
    }
    assert store.materialize(run_id, "inputs/mesh.txt").read_text() == "mesh\n"
    store.release_hold(run_id, prepared["reader_hold"])


def test_replay_without_git_base_releases_reader_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run_id, project = make_replay_record(tmp_path, monkeypatch)
    git_dir = project / ".git"
    unavailable = project / ".git-unavailable"
    git_dir.rename(unavailable)

    with pytest.raises(RuntimeError, match="Git base is unavailable"):
        _capture.prepare_replay(store, run_id, tmp_path / "replay")

    assert store.projection(run_id)["holds"] == set()


class ProfileSourceCapture(Profile):
    def __init__(self, run: core.Run) -> None:
        self.run = run

    def init(self) -> core.Run:
        return self.run


def run_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[core.Run, Path]:
    entrypoint = tmp_path / "run.py"
    entrypoint.write_text("from liblaf import cherries\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(entrypoint)])
    monkeypatch.setattr(_capture, "_editable_roots", list)
    run = core.Run(store_root=tmp_path / "store", plugins=PluginManager())
    run.repo = None
    return run, entrypoint


def test_source_change_during_execution_is_recorded_as_unstable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, entrypoint = run_for(tmp_path, monkeypatch)

    def experiment() -> None:
        entrypoint.write_text("changed during execution\n")
        run.output("result.txt").write_text("ok\n")

    cherries.main(experiment, profile=ProfileSourceCapture(run))

    assert run.store is not None
    assert run.store.read_record(run.run_id)["record"]["source_stability"] is False


@pytest.mark.skipif(
    not Path("/proc").is_dir(), reason="requires Linux child-process inspection"
)
def test_live_child_writer_prevents_sealing_and_failure_payload_discard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _ = run_for(tmp_path, monkeypatch)
    child: subprocess.Popen[bytes] | None = None

    def experiment() -> None:
        nonlocal child
        output = run.output("result.bin")
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys, time; path = sys.argv[1]; "
                    "open(path, 'ab').write(b'writing'); time.sleep(30)"
                ),
                str(output),
            ]
        )
        time.sleep(0.1)
        message = "experiment failed"
        raise ValueError(message)

    try:
        with pytest.raises(RuntimeError, match="child process is still running"):
            cherries.main(experiment, profile=ProfileSourceCapture(run))
    finally:
        if child is not None:
            child.terminate()
            child.wait(timeout=5)

    assert run.store is not None
    assert run.store.list_records() == []
    assert run.working_dir.is_dir()
    assert any(
        '"recording-incomplete"' in event.read_text()
        for event in (run.store.root / "metadata" / "events").rglob("*.json")
    )


@pytest.mark.skipif(
    not Path("/proc").is_dir(), reason="requires Linux child-process inspection"
)
def test_reparented_writer_prevents_sealing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _ = run_for(tmp_path, monkeypatch)
    writer_pid: int | None = None

    def experiment() -> None:
        nonlocal writer_pid
        output = run.output("result.bin")
        launched = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "child = subprocess.Popen([sys.executable, '-c', "
                    '"import pathlib, sys, time; handle = open(sys.argv[1], '
                    "'ab'); handle.write(b'writing'); handle.flush(); "
                    'time.sleep(30)", sys.argv[1]], '
                    "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                    "print(child.pid)"
                ),
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        writer_pid = int(launched.stdout)
        for _ in range(50):
            if output.exists():
                break
            time.sleep(0.01)
        else:
            pytest.fail("writer did not create the declared output")

    try:
        with pytest.raises(RuntimeError, match="writable work files open"):
            cherries.main(experiment, profile=ProfileSourceCapture(run))
    finally:
        if writer_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(writer_pid, signal.SIGTERM)
            status = Path(f"/proc/{writer_pid}/status")
            for _ in range(50):
                if not status.exists() or "State:\tZ" in status.read_text():
                    break
                time.sleep(0.01)
            else:
                pytest.fail("reparented writer did not stop")

    assert run.store is not None
    assert run.store.list_records() == []
    assert run.working_dir.is_dir()

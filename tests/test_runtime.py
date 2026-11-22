# Copyright (c) 2026 liblaf
from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from liblaf import cherries
from liblaf.cherries._io import RunMeta, read_yaml
from liblaf.cherries._storage import LocalStore

from .conftest import execute, git

FIELDS = {
    field.alias or name
    for name, field in RunMeta.model_fields.items()
    if name != "description"
}


def _assert_artifacts(directory: Path, expected: dict[str, dict[str, bytes]]) -> None:
    artifacts = read_yaml(directory / "run.yaml")["artifacts"]
    assert set(artifacts) == {"inputs", "outputs", "figs"}
    for role in artifacts:
        entries = artifacts[role]
        assert isinstance(entries, list)
        assert len(entries) == len(expected.get(role, {}))
        assert {entry["name"] for entry in entries} == set(expected.get(role, {}))
        for entry in entries:
            payload = expected[role][entry["name"]]
            assert entry == {
                "name": entry["name"],
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
            assert type(entry["size"]) is int
            assert (directory / role / entry["name"]).read_bytes() == payload


@pytest.mark.parametrize(
    ("timezone", "offset"),
    [("Asia/Shanghai", "+08:00"), ("Pacific/Marquesas", "-09:30")],
)
def test_actual_script_records_end_state_paths_metrics_diff_and_native_logs(  # noqa: PLR0915
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    timezone: str,
    offset: str,
) -> None:
    monkeypatch.setenv("TZ", timezone)
    study = repo / "exp/2026/11/15/example"
    (study / "data").mkdir(parents=True)
    (study / "data/input.txt").write_text("before")
    (study / "src").mkdir()
    (study / "src/helper.py").write_text("value = 42\n")
    head = git(repo, "rev-parse", "HEAD")
    index = (repo / ".git/index").read_bytes()
    before = datetime.now(UTC).replace(microsecond=0)
    result = execute(
        repo,
        """from __future__ import annotations
import ctypes
import os
import subprocess
import sys
from pathlib import Path
from liblaf import cherries

class Config(cherries.BaseConfig):
    scale: float = 0.25
    source: Path = cherries.input("input.txt")
    output: Path = cherries.output("nested/result.txt")

def main(cfg: Config):
    assert cfg.source.is_absolute() and cfg.output.is_absolute()
    assert cfg.source == cherries.input("input.txt")
    cfg.source.write_text("end of execution")
    cfg.output.write_text("answer")
    cherries.fig("loss.png").write_bytes(b"figure")
    print("python stdout")
    print("python stderr", file=sys.stderr)
    os.write(1, b"native stdout\\n")
    os.write(2, b"native stderr\\n")
    ctypes.CDLL(None).printf(b"libc buffered text")
    subprocess.run([sys.executable, "-c", "print('subprocess text')"], check=True)
    assert cherries.get_step() == 0
    cherries.log_metrics({"x": 1, "y": 2}, timestamp_ms=0)
    journal = next((cfg.source.parents[6] / "cherries/runs").glob("*/*/*/*.tmp/metrics.jsonl"))
    assert len(journal.read_text().splitlines()) == 2
    cherries.set_step(7)
    cherries.log_metric("x", 3, step=0, timestamp_ms=0)
    assert cherries.get_step() == 7
    cherries.log_metrics({"nan": float("nan"), "inf": float("inf"), "neg": -float("inf")})

if __name__ == "__main__":
    saved = cherries.run(main)
    print(saved)
""",
    )
    directory = Path(result.stdout.strip())
    metadata = read_yaml(directory / "run.yaml")
    assert set(metadata) == FIELDS
    assert metadata["start-time"].endswith(offset)
    assert metadata["end-time"].endswith(offset)
    start_time = datetime.fromisoformat(metadata["start-time"])
    end_time = datetime.fromisoformat(metadata["end-time"])
    assert before <= start_time <= end_time <= datetime.now(UTC)
    assert directory == (
        repo / "cherries/runs" / start_time.strftime("%Y/%m/%d") / metadata["run-id"]
    )
    assert metadata["project-id"] == repo.name
    assert metadata["run-name"] == "10-run"
    assert metadata["commit"] == head
    assert uuid.UUID(metadata["run-id"]).version == 7
    assert metadata["params"] == {
        "scale": 0.25,
        "source": str(study / "data/input.txt"),
        "output": str(study / "data/nested/result.txt"),
    }
    assert (directory / "inputs/input.txt").read_text() == "end of execution"
    assert (directory / "outputs/nested/result.txt").read_text() == "answer"
    _assert_artifacts(
        directory,
        {
            "inputs": {"input.txt": b"end of execution"},
            "outputs": {"nested/result.txt": b"answer"},
            "figs": {"loss.png": b"figure"},
        },
    )
    assert sorted(p.name for p in (directory / "src").iterdir()) == [
        "10-run.py",
        "diff.patch",
    ]
    assert (directory / "src/10-run.py").read_bytes() == (
        study / "src/10-run.py"
    ).read_bytes()
    patch = (directory / "src/diff.patch").read_text()
    assert "exp/2026/11/15/example/src/helper.py" in patch
    assert "value = 42" in patch
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / ".git/index").read_bytes() == index
    assert not git(repo, "for-each-ref", "refs/cherries/")
    assert not (directory / "metrics.jsonl").exists()
    frame = pl.read_parquet(directory / "metrics.parquet")
    assert frame.schema == {
        "key": pl.String,
        "value": pl.Float64,
        "step": pl.Int64,
        "timestamp_ms": pl.Int64,
    }
    assert frame["key"].to_list() == ["x", "y", "x", "nan", "inf", "neg"]
    assert frame["step"].to_list() == [0, 0, 0, 7, 7, 7]
    assert frame["timestamp_ms"].head(3).to_list() == [0, 0, 0]
    assert len(set(frame["timestamp_ms"].tail(3))) == 1
    assert math.isnan(frame["value"][3])
    assert frame["value"].tail(2).to_list() == [math.inf, -math.inf]
    log = (directory / "run.log").read_text()
    for text in [
        "python stdout",
        "python stderr",
        "native stdout",
        "native stderr",
        "libc buffered text",
        "subprocess text",
        "Cherries started",
        "Cherries saved",
    ]:
        assert text in log
    (study / "data/input.txt").write_text("later workspace edit")
    assert (directory / "inputs/input.txt").read_text() == "end of execution"
    assert read_yaml(directory / "run.yaml")["artifacts"] == metadata["artifacts"]
    assert (directory / "inputs/input.txt").stat().st_ino != (
        study / "data/input.txt"
    ).stat().st_ino
    LocalStore(repo).get(directory.name).verify()


def test_clean_committed_script_omits_diff_patch(repo: Path) -> None:
    entry = repo / "exp/2026/11/15/example/src/10-run.py"
    entry.parent.mkdir(parents=True)
    entry.write_text(
        """from liblaf import cherries
def main():
    cherries.output("result.txt").write_text("clean")
if __name__ == "__main__":
    print(cherries.run(main))
"""
    )
    git(repo, "add", str(entry))
    git(repo, "commit", "-m", "add script")
    result = execute(repo, entry.read_text())
    directory = Path(result.stdout.strip())
    assert [p.name for p in (directory / "src").iterdir()] == ["10-run.py"]
    LocalStore(repo).get(directory.name).verify()


def test_registered_directories_have_relative_file_manifests(repo: Path) -> None:
    study = repo / "exp/2026/11/15/example"
    source = study / "data/meshes"
    (source / "nested/empty").mkdir(parents=True)
    (source / "nested/model.lfs").write_bytes(b"mesh source")
    result = execute(
        repo,
        """from pathlib import Path
from liblaf import cherries

class Config(cherries.BaseConfig):
    meshes: Path = cherries.input("meshes")
    export: Path = cherries.output("export")

def main(cfg: Config):
    assert cherries.input(cfg.meshes) == cfg.meshes
    cherries.output("wholly-empty").mkdir()
    (cfg.export / "nested/empty").mkdir(parents=True)
    (cfg.export / "nested/result.lfs").write_bytes(b"computed mesh")
    (cfg.export / "empty.bin").write_bytes(b"")
    panels = cherries.fig("panels")
    (panels / "nested/empty").mkdir(parents=True)
    (panels / "nested/result.png").write_bytes(b"rendered figure")

if __name__ == "__main__":
    print(cherries.run(main))
""",
    )
    directory = Path(result.stdout.strip())
    _assert_artifacts(
        directory,
        {
            "inputs": {"meshes/nested/model.lfs": b"mesh source"},
            "outputs": {
                "export/nested/result.lfs": b"computed mesh",
                "export/empty.bin": b"",
            },
            "figs": {"panels/nested/result.png": b"rendered figure"},
        },
    )
    for role in ("inputs", "outputs", "figs"):
        assert all(
            any(path.iterdir())
            for path in (directory / role).rglob("*")
            if path.is_dir()
        )
    LocalStore(repo).get(directory.name).verify()


def test_manifest_hashes_saved_copy_when_workspace_changes_during_collection(
    repo: Path,
) -> None:
    result = execute(
        repo,
        """from liblaf import cherries
from liblaf.cherries import _runtime

output = cherries.output("result.txt")
original_copy = _runtime.copy

def copy(source, destination):
    result = original_copy(source, destination)
    source.write_bytes(b"later workspace edit")
    return result

_runtime.copy = copy

def main():
    output.write_bytes(b"completed result")

if __name__ == "__main__":
    print(cherries.run(main))
""",
    )
    directory = Path(result.stdout.strip())
    assert (
        repo / "exp/2026/11/15/example/data/result.txt"
    ).read_bytes() == b"later workspace edit"
    _assert_artifacts(directory, {"outputs": {"result.txt": b"completed result"}})
    LocalStore(repo).get(directory.name).verify()


def test_failure_preserves_unfinished_record_and_original_exception(repo: Path) -> None:
    result = execute(
        repo,
        """from liblaf import cherries
def main():
    cherries.output("partial.txt").write_text("partial")
    cherries.output("not-yet-created.txt")
    cherries.log_metric("loss", 1.0)
    raise ValueError("experiment failed")
if __name__ == "__main__":
    cherries.run(main)
""",
        check=False,
    )
    assert result.returncode != 0
    assert "ValueError: experiment failed" in result.stderr
    store = LocalStore(repo)
    assert not store.runs()
    (run,) = store.runs(unfinished=True)
    assert run.directory.suffix == ".tmp"
    assert (run.directory / "outputs/partial.txt").read_text() == "partial"
    assert "experiment failed" in (run.directory / "run.log").read_text()
    assert run.metadata["commit"]
    assert set(run.metadata) == FIELDS
    _assert_artifacts(run.directory, {"outputs": {"partial.txt": b"partial"}})
    run.verify()


def test_manual_start_end_and_no_metrics_or_config(repo: Path) -> None:
    execute(
        repo,
        """from liblaf import cherries
result = cherries.output("result.txt")
if __name__ == "__main__":
    cherries.start(params={"n": 42})
    result.write_text("42")
    cherries.end()
    print("restored stdout")
""",
    )
    (record,) = (repo / "cherries/runs").glob("*/*/*/*/run.yaml")
    directory = record.parent
    assert read_yaml(directory / "run.yaml")["params"] == {"n": 42}
    _assert_artifacts(directory, {"outputs": {"result.txt": b"42"}})
    assert {p.name for p in directory.iterdir()} == {
        "run.yaml",
        "run.log",
        "src",
        "outputs",
    }
    assert not hasattr(cherries, "Input")
    assert not hasattr(cherries, "Store")
    assert not hasattr(cherries, "upload")


def test_dirty_lfs_fails_fast_at_start_and_if_created_mid_run(repo: Path) -> None:
    (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-m", "lfs rule")

    # Pre-existing dirty LFS fails fast at start() before running main() or creating .tmp.
    (repo / "dirty.bin").write_bytes(b"uncommitted lfs")
    result = execute(
        repo,
        """from liblaf import cherries
def main():
    raise AssertionError("main should not run when preflight fails")
if __name__ == "__main__":
    cherries.run(main)
""",
        check=False,
    )
    assert result.returncode != 0
    assert "Dirty Git LFS" in result.stderr
    assert not (repo / "cherries").exists()
    (repo / "dirty.bin").unlink()

    # Dirty LFS created during main() is rejected at end() and retains .tmp diagnostics.
    result = execute(
        repo,
        """from pathlib import Path
from liblaf import cherries
def main():
    repo_root = Path(__file__).resolve().parents[6]
    (repo_root / "midrun.bin").write_bytes(b"created mid-run")
    cherries.output("result.txt").write_text("done")
if __name__ == "__main__":
    cherries.run(main)
""",
        check=False,
    )
    assert result.returncode != 0
    assert "Dirty Git LFS" in result.stderr
    store = LocalStore(repo)
    assert not store.runs()
    assert len(store.runs(unfinished=True)) == 1


@pytest.mark.parametrize(
    "mode", ["automatic", "manual", "failure", "recording-failure"]
)
@pytest.mark.parametrize(
    ("start_time", "end_time", "collection_time", "date_path"),
    [
        (
            "2026-01-02 00:01:00+08:00",
            "2026-01-03 00:03:12+08:00",
            "2026-01-03 00:59:00+08:00",
            "2026/01/02",
        ),
        (
            "2026-12-31 23:59:00-09:30",
            "2027-01-01 00:03:12-09:30",
            "2027-01-01 00:59:00-09:30",
            "2026/12/31",
        ),
    ],
    ids=["positive-offset-near-midnight", "negative-offset-year-end"],
)
def test_lifecycle_times_exclude_artifact_collection(
    repo: Path,
    mode: str,
    start_time: str,
    end_time: str,
    collection_time: str,
    date_path: str,
) -> None:
    result = execute(
        repo,
        f"""from pathlib import Path
from liblaf import cherries
from liblaf.cherries import _runtime
from liblaf.cherries._io import read_yaml
from liblaf.cherries._storage import LocalStore

clock = {{"value": {start_time!r}}}
_runtime.now = lambda: clock["value"]
repo = Path(__file__).resolve().parents[6]
result = cherries.output("result.txt")
original_copy = _runtime.copy

def copy(source, destination):
    clock["value"] = {collection_time!r}
    pending = next((repo / "cherries/runs").glob("*/*/*/*.tmp/run.yaml"))
    assert read_yaml(pending)["end-time"] == {end_time!r}
    return original_copy(source, destination)

_runtime.copy = copy

def main():
    pending = next((repo / "cherries/runs").glob("*/*/*/*.tmp/run.yaml"))
    metadata = read_yaml(pending)
    assert pending.parent == repo / "cherries/runs" / {date_path!r} / (metadata["run-id"] + ".tmp")
    assert metadata["start-time"] == {start_time!r}
    assert metadata["end-time"] is None
    assert metadata["artifacts"] == {{"inputs": [], "outputs": [], "figs": []}}
    LocalStore(repo).get(pending.parent).verify()
    if {mode!r} != "recording-failure":
        result.write_text("result")
    clock["value"] = {end_time!r}
    if {mode!r} == "failure":
        raise ValueError("experiment failed")

if __name__ == "__main__":
    if {mode!r} == "manual":
        cherries.start()
        main()
        cherries.end()
    else:
        cherries.run(main)
""",
        check=False,
    )
    assert (result.returncode == 0) == (mode in {"automatic", "manual"})
    (record,) = (repo / "cherries/runs").glob("*/*/*/*/run.yaml")
    directory = record.parent
    data = read_yaml(record)
    assert data["start-time"] == start_time
    assert data["end-time"] == end_time
    unfinished = mode in {"failure", "recording-failure"}
    expected_name = data["run-id"] + (".tmp" if unfinished else "")
    assert directory == repo / "cherries/runs" / date_path / expected_name
    if not unfinished:
        assert not (directory.parent / (data["run-id"] + ".tmp")).exists()


def test_tmp_is_workspace_only_and_cannot_escape_its_root(repo: Path) -> None:
    study = repo / "exp/2026/11/15/example"
    temporary = study / "tmp/debug/nested.txt"
    temporary.parent.mkdir(parents=True)
    temporary.write_text("tracked intermediate")
    git(repo, "add", "--force", str(temporary))
    git(repo, "commit", "-m", "tracked intermediate")
    result = execute(
        repo,
        """from pathlib import Path
from liblaf import cherries

class Config(cherries.BaseConfig):
    intermediate: Path = cherries.tmp("debug/nested.txt")

def main(cfg: Config):
    study = Path(__file__).resolve().parent.parent
    assert cfg.intermediate == study / "tmp/debug/nested.txt"
    assert cherries.tmp(cfg.intermediate) == cfg.intermediate
    cfg.intermediate.write_text("updated intermediate")
    cherries.tmp("new/deep/intermediate.txt").write_text("new intermediate")
    (study / "tmp/link").symlink_to(study / "data", target_is_directory=True)
    for path in (".", "../data/escaped.txt", study / "data/escaped.txt", "link/escaped.txt"):
        try:
            cherries.tmp(path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"tmp accepted an escaping path: {path}")
    for fn in (cherries.input, cherries.output, cherries.fig):
        try:
            fn(".")
        except ValueError:
            pass
        else:
            raise AssertionError(f"{fn.__name__} accepted root directory")
    cherries.output("result.txt").write_text("saved result")

if __name__ == "__main__":
    print(cherries.run(main))
""",
    )
    directory = Path(result.stdout.strip())
    _assert_artifacts(directory, {"outputs": {"result.txt": b"saved result"}})
    assert temporary.read_text() == "updated intermediate"
    assert not (directory / "tmp").exists()
    patch = (directory / "src/diff.patch").read_text()
    script_rel = "exp/2026/11/15/example/src/10-run.py"
    headers = [line for line in patch.splitlines() if line.startswith("diff --git ")]
    assert headers == [f"diff --git a/{script_rel} b/{script_rel}"]
    LocalStore(repo).get(directory.name).verify()


@pytest.mark.parametrize("fail", [False, True])
def test_debug_runs_config_once_without_recording_and_keeps_console_output(
    repo: Path, monkeypatch: pytest.MonkeyPatch, *, fail: bool
) -> None:
    monkeypatch.setenv("DEBUG", "1")
    study = repo / "exp/2026/11/15/example"
    (study / "data").mkdir(parents=True)
    (study / "data/input.txt").write_text("input")
    head = git(repo, "rev-parse", "HEAD")
    index = (repo / ".git/index").read_bytes()
    result = execute(
        repo,
        f"""import os
import subprocess
import sys
from pathlib import Path
from pydantic import ConfigDict
from liblaf import cherries
from liblaf.cherries import _runtime

def forbidden(*args, **kwargs):
    raise AssertionError("debug attempted recording")

_runtime._git.root = forbidden
_runtime._git.preflight = forbidden
_runtime._git.capture = forbidden
_runtime._Capture = forbidden
_runtime.copy = forbidden
_runtime.collect_artifacts = forbidden
_runtime.write_yaml = forbidden
_runtime.pl.scan_ndjson = forbidden

class Config(cherries.BaseConfig):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    opaque: object = object()
    source: Path = cherries.input("input.txt")
    result: Path = cherries.output("nested/result.txt")
    intermediate: Path = cherries.tmp("debug/nested.txt")

    def model_dump(self, **kwargs):
        raise AssertionError("debug serialized parameters")

calls = 0
original_error = ValueError("original debug failure")

def main(cfg: Config):
    global calls
    calls += 1
    assert isinstance(cfg, Config)
    assert cfg.source.is_absolute() and cfg.source.read_text() == "input"
    assert cherries.get_step() == 0
    os.environ["DEBUG"] = "0"
    cherries.set_step(7)
    cherries.log_metric("loss", 1)
    cherries.log_metrics({{"a": 2, "b": 3}}, step=42, timestamp_ms=0)
    assert cherries.get_step() == 7
    cfg.result.write_text("debug result")
    cfg.intermediate.write_text("debug intermediate")
    cherries.fig("nested/figure.png").write_bytes(b"debug figure")
    print("python stdout")
    print("python stderr", file=sys.stderr)
    os.write(1, b"native stdout\\n")
    os.write(2, b"native stderr\\n")
    subprocess.run([sys.executable, "-c", "print('subprocess stdout')"], check=True)
    if {fail!r}:
        raise original_error

if __name__ == "__main__":
    try:
        assert cherries.run(main) is None
    except ValueError as error:
        assert error is original_error
        assert calls == 1
        raise
    assert calls == 1
""",
        check=False,
    )
    assert (result.returncode != 0) == fail
    for text in ("python stdout", "native stdout", "subprocess stdout"):
        assert text in result.stdout
    for text in ("python stderr", "native stderr"):
        assert text in result.stderr
    if fail:
        assert "ValueError: original debug failure" in result.stderr
    assert "debug attempted recording" not in result.stderr
    assert not (repo / "cherries").exists()
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / ".git/index").read_bytes() == index
    assert (study / "data/nested/result.txt").read_text() == "debug result"
    assert (study / "figs/nested/figure.png").read_bytes() == b"debug figure"
    assert (study / "tmp/debug/nested.txt").read_text() == "debug intermediate"


def test_manual_debug_outside_git_and_next_run_records(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEBUG", "1")
    outside = tmp_path / "outside-git"
    result = execute(
        outside,
        """import os
from liblaf import cherries

cherries.start(params={"not_serializable": object()})
assert cherries.get_step() == 0
cherries.set_step(9)
os.environ["DEBUG"] = "0"
cherries.log_metrics({"loss": 1})
cherries.output("nested/result.txt").write_text("manual debug")
cherries.tmp("debug/intermediate.txt").write_text("intermediate")
assert cherries.get_step() == 9
cherries.end()
print("manual debug ended")
""",
    )
    assert result.stdout.strip() == "manual debug ended"
    assert not (outside / "cherries").exists()
    execute(
        repo,
        """import os
from liblaf import cherries
cherries.start()
cherries.set_step(9)
cherries.output("debug-only-missing.txt")
cherries.end()
os.environ["DEBUG"] = "0"
def main():
    assert cherries.get_step() == 0
    cherries.output("result.txt").write_text("recorded")
assert cherries.run(main) is not None
""",
    )
    (record,) = LocalStore(repo).runs()
    _assert_artifacts(record.directory, {"outputs": {"result.txt": b"recorded"}})


@pytest.mark.parametrize("value", ["0", "true", "01"])
def test_only_exact_debug_one_disables_recording(
    repo: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DEBUG", value)
    execute(
        repo,
        """import os
from liblaf import cherries
def main():
    os.environ["DEBUG"] = "1"
    cherries.log_metric("recorded", 1)
    cherries.output("result.txt").write_text("recorded")
assert cherries.run(main) is not None
""",
    )
    (record,) = LocalStore(repo).runs()
    assert (record.directory / "metrics.parquet").exists()
    _assert_artifacts(record.directory, {"outputs": {"result.txt": b"recorded"}})


def test_lifecycle_helpers_require_an_active_run() -> None:
    with pytest.raises(RuntimeError, match="No active Cherries run"):
        cherries.get_step()
    with pytest.raises(RuntimeError, match="No active Cherries run"):
        cherries.end()

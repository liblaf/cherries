# Copyright (c) 2026 liblaf
"""Command boundary behavior for the record-management CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from liblaf.cherries import _cli, _storage


def _record(number: int, **changes: object) -> SimpleNamespace:
    metadata = {
        "project-id": "study",
        "run-id": f"00000000-0000-7000-8000-{number:012d}",
        "run-name": "mesh check",
        "description": "completed mesh roundtrip",
        "start-time": "2026-11-15 08:00:00+08:00",
        "end-time": "2026-11-15 08:03:12+08:00",
        "tags": ["checked", "mesh"],
        "params": {"mesh": {"count": 42}, "optional": None},
        "commit": "a" * 40,
        "metadata": {},
        "artifacts": {"inputs": [], "outputs": [], "figs": []},
        **changes,
    }
    return SimpleNamespace(id=metadata["run-id"], metadata=metadata)


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    local = Mock(project_id="study")
    remote = Mock()
    local_class = Mock(return_value=local)
    remote_class = Mock(return_value=remote)
    monkeypatch.setattr(_storage, "LocalStore", local_class)
    monkeypatch.setattr(_storage, "RemoteStore", remote_class)
    return SimpleNamespace(
        local=local, remote=remote, local_class=local_class, remote_class=remote_class
    )


def test_list_filters_before_limit_and_returns_only_yaml_objects(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    older = _record(1)
    newer = _record(3)
    stores.local.runs.return_value = [
        _record(4, tags=["mesh"]),
        older,
        _record(5, description="other", **{"run-name": "other"}),
        newer,
        _record(6, params={"mesh": {"count": 99}, "optional": None}),
    ]
    assert (
        _cli.main(
            [
                "list",
                "--tag",
                "checked",
                "--tag",
                "mesh",
                "--param",
                'mesh={"count":42}',
                "--param",
                "optional=null",
                "--search",
                "roundtrip",
                "--limit",
                "1",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == [newer.metadata]
    stores.local.runs.assert_called_once_with(unfinished=False)


def test_repeated_parameter_filters_are_all_required(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    stores.local.runs.return_value = [_record(1, params={"count": 2})]
    assert (
        _cli.main(
            [
                "list",
                "--param",
                "count=1",
                "--param",
                "count=2",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == []


def test_unfinished_list_and_missing_null_parameter(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    stores.local.runs.return_value = [_record(1, params={}), _record(2)]
    assert (
        _cli.main(
            [
                "list",
                "--unfinished",
                "--param",
                "optional=null",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == [_record(2).metadata]
    stores.local.runs.assert_called_once_with(unfinished=True)


def test_remote_read_outside_repo_and_logical_files(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    record = Mock()
    record.files.return_value = ["outputs/mesh.vtu", "outputs/empty"]
    stores.remote.get.return_value = record
    assert (
        _cli.main(
            [
                "--remote",
                str(tmp_path),
                "--project-id",
                "study",
                "files",
                "run-id",
                "outputs",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == ["outputs/mesh.vtu", "outputs/empty"]
    stores.local_class.assert_not_called()
    stores.remote_class.assert_called_once_with(tmp_path, "study")
    record.files.assert_called_once_with("outputs")


def test_show_json_preserves_metadata(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _record(1)
    stores.local.get.return_value = record
    assert _cli.main(["show", record.id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == record.metadata


def test_push_and_pull_have_fixed_source_and_destination(
    stores: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_record = stores.local.get.return_value
    remote_record = stores.remote.get.return_value
    push = Mock(return_value=tmp_path / "remote-run")
    pull = Mock(return_value=tmp_path / "local-run")
    monkeypatch.setattr(_storage, "push", push)
    monkeypatch.setattr(_storage, "pull", pull)
    prefix = ["--remote", str(tmp_path / "remote")]
    assert _cli.main([*prefix, "push", "run-id"]) == 0
    push.assert_called_once_with(local_record, stores.remote)
    assert capsys.readouterr().out.strip() == str(tmp_path / "remote-run")
    assert _cli.main([*prefix, "pull", "run-id", "--overwrite"]) == 0
    pull.assert_called_once_with(remote_record, stores.local, overwrite=True)
    assert capsys.readouterr().out.strip() == str(tmp_path / "local-run")


def test_edit_decodes_json_values_and_uses_remote(
    stores: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = stores.remote.get.return_value
    record.edit.return_value = tmp_path / "run"
    assert (
        _cli.main(
            [
                "--remote",
                str(tmp_path),
                "--project-id",
                "study",
                "edit",
                "run-id",
                "--name",
                "result",
                "--clear-description",
                "--add-tag",
                "checked",
                "--remove-tag",
                "pending",
                "--metadata",
                'report={"ok":true}',
                "--unset-metadata",
                "old",
            ]
        )
        == 0
    )
    record.edit.assert_called_once_with(
        name="result",
        description=None,
        clear_description=True,
        add_tags=["checked"],
        remove_tags=["pending"],
        metadata={"report": {"ok": True}},
        unset_metadata=["old"],
    )
    assert capsys.readouterr().out.strip() == str(tmp_path / "run")


def test_remote_gc_does_not_require_local_repository(
    stores: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stores.remote.gc.return_value = {"objects": 2, "bytes": 80}
    assert _cli.main(["--remote", str(tmp_path), "gc", "--dry-run"]) == 0
    stores.local_class.assert_not_called()
    stores.remote_class.assert_called_once_with(tmp_path, None)
    stores.remote.gc.assert_called_once_with(dry_run=True)
    assert "bytes: 80" in capsys.readouterr().out


def test_operational_failure_is_nonzero_and_only_on_stderr(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    stores.local.get.side_effect = FileNotFoundError("run is missing")
    assert _cli.main(["verify", "missing"]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "run is missing" in captured.err


def test_real_local_to_remote_record_flow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An edited record remains queryable as logical files after CAS upload."""
    import subprocess

    import yaml

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], text=True
        ).strip()

    git("init", "--quiet")
    script = repo / "run.py"
    script.write_text("print('experiment')\n")
    git("add", "run.py")
    git(
        "-c",
        "user.name=CLI Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--quiet",
        "-m",
        "initial",
    )
    data = _record(1, commit=git("rev-parse", "HEAD")).metadata
    run_id = data["run-id"]
    directory = repo / "cherries/runs/2026/11/15" / run_id
    (directory / "src").mkdir(parents=True)
    (directory / "src" / script.name).write_bytes(script.read_bytes())
    (directory / "outputs").mkdir()
    payload = b"mesh payload\x00\xff"
    (directory / "outputs" / "mesh.bin").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    data["artifacts"]["outputs"] = [
        {"name": "mesh.bin", "sha256": digest, "size": len(payload)}
    ]
    (directory / "run.log").write_text("completed\n")
    (directory / "run.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    git("update-ref", f"refs/cherries/runs/{run_id}", data["commit"])

    local = ["--repo", str(repo), "--project-id", "study"]
    assert (
        _cli.main(
            [
                *local,
                "edit",
                run_id,
                "--name",
                "checked mesh",
                "--description",
                "Mesh passed",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == str(directory)
    assert (
        _cli.main(
            [
                *local,
                "list",
                "--search",
                "Mesh passed",
                "--tag",
                "checked",
                "--param",
                'mesh={"count":42}',
                "--json",
            ]
        )
        == 0
    )
    [listed] = json.loads(capsys.readouterr().out)
    assert listed["run-name"] == "checked mesh"
    assert listed["commit"] == data["commit"]

    remote = tmp_path / "remote"
    assert _cli.main([*local, "--remote", str(remote), "push", run_id]) == 0
    remote_directory = remote / "projects/study/runs/2026/11/15" / run_id
    assert capsys.readouterr().out.strip() == str(remote_directory)
    assert not (remote_directory / "outputs").exists()
    assert not (remote_directory / "inputs").exists()
    assert not (remote_directory / "figs").exists()
    assert (
        yaml.safe_load((remote_directory / "run.yaml").read_text())["artifacts"]
        == data["artifacts"]
    )
    assert (
        remote / "objects/sha256" / digest[:2] / digest[2:4] / digest
    ).read_bytes() == payload
    remote_args = ["--remote", str(remote), "--project-id", "study"]
    assert _cli.main([*remote_args, "list", "--search", "Mesh passed", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [listed]
    assert _cli.main([*remote_args, "files", run_id, "outputs", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == ["outputs/mesh.bin"]
    destination = tmp_path / "restored.bin"
    assert (
        _cli.main(
            [
                *remote_args,
                "get",
                run_id,
                "outputs/mesh.bin",
                "--output",
                str(destination),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == str(destination)
    assert destination.read_bytes() == payload

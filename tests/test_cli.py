# Copyright (c) 2026 liblaf
"""Command boundary behavior for the record-management CLI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from liblaf.cherries import _cli, _restic, _storage


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
    monkeypatch.setattr(_restic, "ResticStore", remote_class)
    return SimpleNamespace(
        local=local, remote=remote, local_class=local_class, remote_class=remote_class
    )


def test_list_and_show_cli_routing(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    newer = _record(3)
    stores.local.list_metadata.return_value = [newer.metadata]
    assert (
        _cli.main(
            [
                "list",
                "--tag",
                "checked",
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
    stores.local.list_metadata.assert_called_once_with(
        tags=["checked"],
        params=[("mesh", {"count": 42}), ("optional", None)],
        search="roundtrip",
        limit=1,
        unfinished=False,
    )

    stores.local.show.return_value = newer.metadata
    assert _cli.main(["list"]) == 0
    assert newer.id in capsys.readouterr().out
    assert _cli.main(["show", newer.id]) == 0
    assert f"run-id: {newer.id}" in capsys.readouterr().out
    assert _cli.main(["show", newer.id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == newer.metadata


def test_remote_show_outside_repo(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _record(1)
    stores.remote.show.return_value = record.metadata
    assert (
        _cli.main(
            [
                "--remote",
                "sftp:nas:/archive/cherries",
                "--project-id",
                "study",
                "show",
                record.id,
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == record.metadata
    stores.local_class.assert_not_called()
    stores.remote_class.assert_called_once_with("sftp:nas:/archive/cherries", "study")


def test_path_and_verify_are_local_only(
    stores: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stores.local.get.return_value = SimpleNamespace(
        directory=tmp_path / "run", verify=Mock()
    )
    assert _cli.main(["path", "run-id"]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / "run")

    assert _cli.main(["verify", "run-id"]) == 0
    stores.local.get.return_value.verify.assert_called_once_with()

    assert _cli.main(["--remote", str(tmp_path), "path", "run-id"]) != 0
    assert "local" in capsys.readouterr().err

    assert _cli.main(["--remote", str(tmp_path), "verify", "run-id"]) != 0
    assert "restic check" in capsys.readouterr().err


def test_push_and_pull_route_through_restic_store(
    stores: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local_record = stores.local.get.return_value
    stores.remote.push.return_value = "abcdef01"
    stores.remote.pull.return_value = tmp_path / "local-run"
    prefix = ["--remote", str(tmp_path / "remote")]
    assert _cli.main([*prefix, "push", "run-id"]) == 0
    stores.remote.push.assert_called_once_with(local_record)
    assert capsys.readouterr().out.strip() == "abcdef01"
    assert _cli.main([*prefix, "pull", "run-id", "--overwrite"]) == 0
    stores.remote.pull.assert_called_once_with("run-id", stores.local, overwrite=True)
    assert capsys.readouterr().out.strip() == str(tmp_path / "local-run")


def test_edit_and_add_are_local_only(
    stores: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = stores.local.get.return_value
    record.edit.return_value = tmp_path / "run"
    assert (
        _cli.main(
            [
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

    assert _cli.main(["--remote", str(tmp_path), "edit", "run-id", "--name", "x"]) != 0
    assert "immutable" in capsys.readouterr().err

    source = tmp_path / "plot.png"
    record.add.return_value = tmp_path / "run/figs/plot.png"
    assert _cli.main(["add", "run-id", str(source), "--as", "figs/plot.png"]) == 0
    record.add.assert_called_once_with(source.resolve(), "figs/plot.png")
    assert capsys.readouterr().out.strip() == str(tmp_path / "run/figs/plot.png")
    assert (
        _cli.main(
            [
                "--remote",
                str(tmp_path),
                "add",
                "run-id",
                str(source),
                "--as",
                "figs/plot.png",
            ]
        )
        != 0
    )
    assert "immutable" in capsys.readouterr().err


def test_lineage_and_prune_cli_routing(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = _record(2)
    stores.local.lineage.return_value = [kept.metadata]
    stores.local.prune.return_value = {"keep": [kept.id], "remove": ["old"]}
    assert _cli.main(["lineage", "--tag", "selected", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [kept.metadata]
    stores.local.lineage.assert_called_once_with([], tags=["selected"])

    assert _cli.main(["prune", "--tag", "selected", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"keep": [kept.id], "remove": ["old"]}
    stores.local.prune.assert_called_once_with(
        [], tags=["selected"], unfinished=False, dry_run=True
    )


def test_remote_gc_requires_remote_and_skips_local_repo(
    stores: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli.main(["gc"]) != 0
    assert "--remote is required" in capsys.readouterr().err

    stores.remote.gc.return_value = "pruned\n"
    assert _cli.main(["--remote", str(tmp_path), "gc", "--dry-run"]) == 0
    stores.local_class.assert_not_called()
    stores.remote_class.assert_called_once_with(str(tmp_path), None)
    stores.remote.gc.assert_called_once_with(dry_run=True)
    assert capsys.readouterr().out == "pruned\n"


def test_operational_failure_is_nonzero_and_only_on_stderr(
    stores: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    stores.local.get.side_effect = FileNotFoundError("run is missing")
    assert _cli.main(["verify", "missing"]) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "run is missing" in captured.err


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is unavailable")
def test_real_cli_local_to_restic_flow(
    repo: Path, saved: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = saved.name
    local = ["--repo", str(repo), "--project-id", repo.name]
    assert _cli.main([*local, "path", run_id]) == 0
    assert capsys.readouterr().out.strip() == str(saved)

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
                "--add-tag",
                "selected",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == str(saved)

    remote = tmp_path / "restic-remote"
    assert _cli.main([*local, "--remote", str(remote), "push", run_id]) == 0
    assert capsys.readouterr().out.strip()

    assert (
        _cli.main(["--remote", str(remote), "--project-id", "other", "list", "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out) == []

    remote_args = ["--remote", str(remote), "--project-id", repo.name]
    assert _cli.main([*remote_args, "list", "--search", "Mesh passed", "--json"]) == 0
    [listed] = json.loads(capsys.readouterr().out)
    assert listed["run-name"] == "checked mesh"
    assert _cli.main([*remote_args, "show", run_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == listed

    assert _cli.main([*local, "remove", run_id]) == 0
    assert not saved.exists()
    assert _cli.main([*local, "--remote", str(remote), "pull", run_id]) == 0
    assert capsys.readouterr().out.strip() == str(saved)
    assert (saved / "outputs/result.txt").read_text() == "shared contents"

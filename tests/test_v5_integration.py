# Copyright (c) 2026 liblaf
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from liblaf import cherries
from liblaf.cherries._cli import main as cli_main
from liblaf.cherries.records import IntegrityError as LegacyIntegrityError
from liblaf.cherries.records import Store as LegacyStore
from liblaf.cherries.store import _store as store_module
from liblaf.cherries.store._import import import_runs, inspect_source
from liblaf.cherries.store._io import hash_file, read_yaml, write_yaml
from liblaf.cherries.store._source import archive_snapshot, checkout_source
from liblaf.cherries.store._store import pointer_bytes


def _project(tmp_path: Path) -> cherries.Project:
    repository = tmp_path / "code"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (repository / "solver.py").write_text("# source\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--quiet", "-m", "source"], check=True
    )
    store = cherries.Store.create(tmp_path / "store", cache_root=tmp_path / "cache")
    return store.projects.add("physics", repo=repository)


def test_public_context_helpers_and_visualization_pin(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = tmp_path / "input.vtu"
    source.write_text("mesh")
    with cherries.run(project=project, name="fit", parameters={"steps": 2}) as active:
        staged = cherries.input(source)
        cherries.output("result.vtu").write_text(staged.read_text() + "-result")
        cherries.log_metrics({"loss": 0.1}, step=2)
        assert cherries.get_metric("loss")["value"].to_list() == [0.1]
        assert cherries.get_params() == {"steps": 2}
        assert cherries.get_param("steps") == 2
        print("fit log")
    assert active.result.saved
    saved = project.runs.get(active.id)
    assert "fit log" in (saved.directory / "run.log").read_text()
    pinned = saved.file("outputs/result.vtu").ref()
    replacement = tmp_path / "replacement.vtu"
    replacement.write_text("new result")
    with saved.edit() as edit:
        edit.add_file(replacement, path="outputs/result.vtu")
    with project.run(name="view", kind="visualization") as view:
        assert view.input(pinned, name="mesh.vtu").read_text() == "mesh-result"
        view.figure("front.png").write_bytes(b"image")
    assert project.runs.get(view.id).metadata["sources"][0]["oid"] == pinned.oid
    with pytest.raises(cherries.ConflictError):
        project.runs.delete(saved.id, dry_run=False)


def test_legacy_recorder_cannot_initialize_or_mutate_a_new_store(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    deferred = LegacyStore(root)
    store = cherries.Store.create(root)
    before = {
        str(path.relative_to(root)): hash_file(path)
        for path in root.rglob("*")
        if path.is_file()
    }
    with pytest.raises(LegacyIntegrityError, match="project/run"):
        LegacyStore(root)
    with pytest.raises(LegacyIntegrityError, match="project/run"):
        deferred.ensure_initialized()
    after = {
        str(path.relative_to(root)): hash_file(path)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert not (root / "collection.json").exists()
    (root / "collection.json").write_text("{}")
    with pytest.raises(cherries.IntegrityError, match="mixed"):
        cherries.Store.open(store.root)


def test_legacy_import_preserves_ids_bytes_and_source_readonly(tmp_path: Path) -> None:
    project = _project(tmp_path)
    legacy = LegacyStore(tmp_path / "legacy")
    work = legacy.start_work("original-run")
    (work / "outputs").mkdir()
    (work / "outputs/result.bin").write_bytes(b"original data")
    (work / "inputs").mkdir()
    (work / "inputs/mesh.dat").write_bytes(b"distinct original input")
    (work / "run.yaml").write_text("original run.yaml payload")
    (work / "legacy").mkdir()
    (work / "legacy/record.json").write_text("original nested evidence")
    legacy.seal(
        "original-run",
        {"name": "old", "execution": {"status": "succeeded", "exit_code": 0}},
        work,
    )
    before = {
        str(p.relative_to(legacy.root)): hash_file(p)
        for p in legacy.root.rglob("*")
        if p.is_file()
    }
    assert inspect_source(legacy.root)["format"] == "legacy-collection"
    result = import_runs(project, legacy.root)
    assert result["imported"][0]["run_id"] == "original-run"
    imported = project.runs.get("original-run")
    assert (
        imported.file("outputs/result.bin").materialize().read_bytes()
        == b"original data"
    )
    assert imported.metadata["execution"]["observed_by"] == "legacy-import"
    assert (
        imported.file("inputs/mesh.dat").materialize().read_bytes()
        == b"distinct original input"
    )
    assert imported.metadata["git"]["provenance"] == "legacy-incomplete"
    assert (
        imported.directory / "legacy/files/run.yaml"
    ).read_text() == "original run.yaml payload"
    assert (
        imported.directory / "legacy/files/legacy/record.json"
    ).read_text() == "original nested evidence"
    after = {
        str(p.relative_to(legacy.root)): hash_file(p)
        for p in legacy.root.rglob("*")
        if p.is_file()
    }
    assert before == after
    with pytest.raises(cherries.ConflictError):
        import_runs(project, legacy.root)


def test_migrated_folder_import_real_payload_and_unknown_execution(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = tmp_path / "migrated"
    folder = source / "projects/physics/runs/old-id"
    (folder / "outputs").mkdir(parents=True)
    (folder / "inputs").mkdir()
    (folder / "inputs/raw.dat").write_bytes(b"independent migrated input")
    payload = tmp_path / "payload"
    payload.write_bytes(b"old payload")
    oid, size = hash_file(payload)
    digest = oid[7:]
    obj = source / "objects/sha256" / digest[:2] / digest[2:4] / (digest + ".dat")
    obj.parent.mkdir(parents=True)
    obj.write_bytes(payload.read_bytes())
    (folder / "outputs/item.dat.lfs").write_text(
        f"version https://git-lfs.github.com/spec/v1\noid {oid}\nsize {size}\n"
    )
    parent = source / "projects/physics/runs/parent-id"
    parent.mkdir()
    write_yaml(parent / "run.yaml", {"id": "parent-id", "status": "unknown"})
    write_yaml(
        folder / "run.yaml",
        {
            "id": "old-id",
            "name": "old",
            "status": "unknown",
            "parents": [{"project": "physics", "run": "parent-id"}],
        },
    )
    receipt = import_runs(project, source, ids=["old-id"])
    assert [item["run_id"] for item in receipt["imported"]] == ["parent-id", "old-id"]
    imported = project.runs.get("old-id")
    assert imported.metadata["status"] == "recorded"
    assert (
        imported.file("inputs/raw.dat").materialize().read_bytes()
        == b"independent migrated input"
    )
    assert (
        imported.file("outputs/item.dat").materialize().read_bytes() == b"old payload"
    )
    assert (
        read_yaml(imported.directory / "run.yaml")["legacy"]["source_stability"]
        == "unknown"
    )
    with pytest.raises(cherries.ConflictError):
        project.runs.delete("parent-id", dry_run=False)


def test_orphaned_trash_blocks_gc_and_keeps_its_payload(tmp_path: Path) -> None:
    project = _project(tmp_path)
    data = tmp_path / "data.bin"
    data.write_bytes(b"sole retained bytes")
    stored = project.store.put(data)
    orphan = project.store.root / ".cherries/trash/interrupted/outputs/data.bin.lfs"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(pointer_bytes(stored["oid"], stored["size"]))
    with pytest.raises(cherries.ConflictError, match="trash"):
        project.store.gc(dry_run=False)
    assert (
        project.store.object_path(stored["oid"]).read_bytes() == b"sole retained bytes"
    )


def test_explicit_metric_tail_recovery_retains_bytes_and_can_finish(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    draft = project.runs.create(name="interrupted")
    prefix = b'{"name":"loss","step":1,"timestamp_ms":1,"value":0.5}\n'
    tail = b'{"name":"loss","value":'
    (draft.directory / "metrics.jsonl").write_bytes(prefix + tail)
    with pytest.raises(cherries.IntegrityError):
        draft.save(git={})
    result = project.store.recover(draft.id)
    assert result["ok"]
    recovery = result["metrics_recovery"][0]
    assert Path(recovery["audit"]).read_bytes() == tail
    assert (draft.directory / "metrics.jsonl").read_bytes() == prefix
    assert project.runs.get(draft.id).save(git={}).saved
    assert project.runs.get(draft.id).metrics.scan().collect().height == 1


def test_metric_recovery_rejects_earlier_corruption_and_active_writer(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    with project.run(name="active") as active:
        active.log_metric("loss", 0.2)
        before = (active.directory / "metrics.jsonl").read_bytes()
        assert not project.store.recover(active.id)["ok"]
        assert (active.directory / "metrics.jsonl").read_bytes() == before
    draft = project.runs.create(name="corrupt")
    broken = b'not-json\n{"partial":'
    (draft.directory / "metrics.jsonl").write_bytes(broken)
    receipt = project.store.recover(draft.id)
    assert not receipt["ok"]
    assert (draft.directory / "metrics.jsonl").read_bytes() == broken


def test_resuming_save_uses_archived_source_not_later_worktree(tmp_path: Path) -> None:
    project = _project(tmp_path)
    draft = project.runs.create(name="interrupted after code capture")
    snapshot = archive_snapshot(project, draft.id)
    draft.metadata["git"] = {"start_fingerprint": "initial", "replay_verified": False}
    write_yaml(draft.directory / "run.yaml", draft.metadata)
    (project.repository / "solver.py").write_text("# later code change\n")
    assert project.runs.get(draft.id).save().saved
    saved = project.runs.get(draft.id)
    assert saved.metadata["git"]["commit"] == snapshot["commit"]
    restored = checkout_source(saved, tmp_path / "restored-code")
    assert (restored / "solver.py").read_text() == "# source\n"
    assert saved.metadata["git"]["source_stable"] is None


def test_explicit_discard_policy_reports_intention_and_original_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    project = _project(tmp_path)
    with (  # noqa: PT012 - verify teardown discards the actual partial payload
        pytest.raises(ValueError, match="experiment failed"),
        project.run(name="discard Python", on_error="discard") as context,
    ):
        context.output("partial.bin").write_bytes(b"discard me")
        message = "experiment failed"
        raise ValueError(message)
    assert context.result.discarded
    assert not context.result.saved
    assert not context.directory.exists()
    (project.repository / "cherries.toml").write_text(
        '[project]\nid = "physics"\n[recording]\non_error = "discard"\n'
    )
    arguments = [
        "--store",
        str(project.store.root),
        "--project",
        "physics",
        "--project-dir",
        str(project.repository),
        "--json",
        "run",
        "exec",
        "--name",
        "discard native",
        "--",
        sys.executable,
        "-c",
        "raise SystemExit(7)",
    ]
    assert cli_main(arguments) == 7
    receipt = json.loads(capsys.readouterr().out.splitlines()[-1])["data"]
    assert receipt["discarded"]
    assert not receipt["saved"]
    assert receipt["execution_status"] == "failed"
    assert not Path(receipt["directory"]).exists()


def test_index_rebuild_does_not_hash_unpublished_payloads_or_metric_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    with project.run(name="metrics") as context:
        context.log_metric("loss", 0.2)
    draft = project.runs.create(name="still running")
    draft.output("large.bin").write_bytes(b"unpublished bytes")
    original_hash = store_module.hash_file

    def checked_hash(path: Path) -> tuple[str, int]:
        assert path.suffix not in {".parquet", ".bin"}, "query indexing read raw data"
        return original_hash(path)

    monkeypatch.setattr(store_module, "hash_file", checked_hash)
    project.store.index.rebuild()
    assert len(project.runs.query()) == 2

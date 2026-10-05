# Copyright (c) 2026 liblaf
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from liblaf import cherries
from liblaf.cherries import _capture, _settings, core
from liblaf.cherries._remote import Remote
from liblaf.cherries.core.plugin import PluginManager
from liblaf.cherries.profiles import Profile
from liblaf.cherries.records import Store


class ProfileBare(Profile):
    def init(self) -> core.Run:
        return core.run


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> core.Run:
    script = tmp_path / "experiment.py"
    script.write_text("from liblaf import cherries\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(script)])
    monkeypatch.setattr(_capture, "_editable_roots", list)
    run = core.run
    monkeypatch.setattr(run, "entrypoint", script)
    monkeypatch.setattr(run, "project_dir", tmp_path)
    monkeypatch.setattr(run, "repo", None)
    monkeypatch.setattr(run, "store_root", tmp_path / "store")
    monkeypatch.setattr(run, "plugins", PluginManager())
    monkeypatch.setattr(run, "active", False)
    return run


def test_main_records_stdout_inputs_outputs_and_source(
    runtime: core.Run, tmp_path: Path
) -> None:
    source = tmp_path / "input.txt"
    source.write_text("input")

    def experiment() -> str:
        staged = cherries.input(source)
        assert staged.parent == runtime.working_dir / "inputs"
        cherries.output("result.txt").write_text(staged.read_text() + "-result")
        cherries.temp("cache").write_text("discard")
        print("experiment output")
        cherries.log_metrics({"loss": 0.25})
        return "ok"

    assert cherries.main(experiment, profile=ProfileBare()) == "ok"
    store = runtime.store
    assert store is not None
    saved = store.read_record(runtime.run_id)
    assert saved["record"]["execution"]["exit_code"] == 0
    assert saved["record"]["replay_verified"] is False
    assert not runtime.working_dir.exists()
    assert (
        store.materialize(runtime.run_id, "outputs/result.txt").read_text()
        == "input-result"
    )
    assert (
        "experiment output"
        in store.materialize(runtime.run_id, "logs/stdout.log").read_text()
    )
    assert not any(
        item["path"].startswith("scratch/")
        for item in store.read_manifest(runtime.run_id)["files"]
    )
    assert source.read_text() == "input"


def test_recording_error_is_nonzero_and_retains_work(runtime: core.Run) -> None:
    def experiment() -> None:
        cherries.output("missing.txt")

    with pytest.raises(FileNotFoundError, match="Required output"):
        cherries.main(experiment, profile=ProfileBare())
    assert runtime.working_dir.is_dir()
    assert runtime.store is not None
    assert runtime.store.list_records() == []
    assert runtime.active is False


def test_execution_failure_keeps_diagnostics_but_discards_unsealed_payload(
    runtime: core.Run,
) -> None:
    def experiment() -> None:
        cherries.output("unfinished.bin").write_bytes(b"payload")
        msg = "execution failed"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="execution failed"):
        cherries.main(experiment, profile=ProfileBare())
    assert runtime.store is not None
    assert runtime.store.list_records() == []
    assert not runtime.working_dir.exists()
    events = list((runtime.store.root / "metadata/events").rglob("*.json"))
    assert any("execution-failed" in path.read_text() for path in events)


def test_zero_exit_seals_the_successful_run(runtime: core.Run) -> None:
    def experiment() -> None:
        cherries.output("result.txt").write_text("saved before exit")
        raise SystemExit(0)

    with pytest.raises(SystemExit) as result:
        cherries.main(experiment, profile=ProfileBare())

    assert result.value.code == 0
    assert runtime.store is not None
    record = runtime.store.read_record(runtime.run_id)["record"]
    assert record["execution"] == {"status": "succeeded", "exit_code": 0}
    assert (
        runtime.store.materialize(runtime.run_id, "outputs/result.txt").read_text()
        == "saved before exit"
    )


def test_hash_input_records_parent_and_copies_into_new_run(runtime: core.Run) -> None:
    def first() -> None:
        cherries.output("mesh.txt").write_text("mesh")

    cherries.main(first, profile=ProfileBare())
    parent = runtime.run_id
    store = runtime.store
    assert store is not None
    binding = next(
        item
        for item in store.read_manifest(parent)["files"]
        if item["path"] == "outputs/mesh.txt"
    )

    def second() -> None:
        mesh = cherries.input(binding["asset_id"], name="selected.txt")
        cherries.output("answer.txt").write_text(mesh.read_text())

    cherries.main(second, profile=ProfileBare())
    assert runtime.run_id != parent
    assert store.read_record(runtime.run_id)["parents"] == [parent]
    assert (
        store.materialize(runtime.run_id, "inputs/selected.txt").read_text() == "mesh"
    )


def test_nonfinite_scientific_result_remains_saved_for_manual_review(
    runtime: core.Run,
) -> None:
    def experiment() -> None:
        cherries.log_metric("loss", float("nan"))
        cherries.log_param("tolerance", float("inf"))
        cherries.output("result.txt").write_text("scientific validation pending")

    cherries.main(experiment, profile=ProfileBare())
    assert runtime.store is not None
    record = runtime.store.read_record(runtime.run_id)["record"]
    assert record["execution"]["status"] == "succeeded"
    assert record["validation"]["status"] == "not_evaluated"
    assert record["params"]["tolerance"] == "Infinity"
    metrics = json.loads(
        runtime.store.materialize(runtime.run_id, "logs/metrics.json").read_text()
    )
    assert any(row["value"] == "NaN" for row in metrics)


def test_modified_staged_input_retains_incomplete_work(
    runtime: core.Run, tmp_path: Path
) -> None:
    source = tmp_path / "original.txt"
    source.write_text("original")

    def experiment() -> None:
        staged = cherries.input(source)
        staged.write_text("modified")

    with pytest.raises(RuntimeError, match="input was modified"):
        cherries.main(experiment, profile=ProfileBare())
    assert source.read_text() == "original"
    assert runtime.working_dir.exists()
    assert runtime.store is not None
    assert not runtime.store.list_records()


def test_tree_input_fetches_remote_bundle_into_fresh_machine(
    runtime: core.Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def producer() -> None:
        folder = cherries.output("frames")
        folder.mkdir()
        (folder / "frame.txt").write_text("frame")

    cherries.main(producer, profile=ProfileBare())
    original = runtime.store
    assert original is not None
    parent = runtime.run_id
    [bundle] = original.read_record(parent)["record"]["bundles"]
    remote = Remote(tmp_path / "remote")
    remote.archive(original, parent)
    target = Store(tmp_path / "second-machine")
    target.ensure_initialized(original.collection_id)
    monkeypatch.setattr(runtime, "store_root", target.root)
    monkeypatch.setattr(_settings, "configured_remote", lambda _project: remote)

    def consumer() -> None:
        folder = cherries.input(bundle["asset_id"], name="selected")
        cherries.output("answer.txt").write_text((folder / "frame.txt").read_text())

    cherries.main(consumer, profile=ProfileBare())
    child = target.read_record(runtime.run_id)
    assert child["parents"] == [parent]
    binding = child["record"]["input_bindings"][0]
    assert binding["asset_id"] == bundle["asset_id"]
    assert binding["manifest_digest"] == original.read_record(parent)["manifest_digest"]
    assert (
        target.materialize(runtime.run_id, "outputs/answer.txt").read_text() == "frame"
    )

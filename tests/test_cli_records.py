# Copyright (c) 2026 liblaf
# ruff: noqa: ANN001, ARG002
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries import _cli


class FakeStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.parents: list[tuple[str, str]] = []
        self.events: list[tuple[str, Any]] = []

    def ensure_initialized(
        self, *, collection_id: str | None = None
    ) -> dict[str, str | None]:
        return {"collection_id": collection_id}

    def list_records(self) -> list[str]:
        return ["one", "two"]

    def projection(self, run_id: str) -> dict[str, object]:
        quality = "good" if run_id == "one" else "bad"
        return {"run_id": run_id, "reviews": [{"status": quality}]}

    def resolve_id(self, value: str) -> str:
        return value

    def read_record(self, value: str) -> dict[str, str]:
        return {"run_id": value}

    def read_manifest(self, value: str) -> dict[str, object]:
        return {"files": []}

    def start_work(self, run_id: str, metadata: Any = None) -> Path:
        path = self.root / "work" / run_id
        path.mkdir(parents=True)
        return path

    def register_parent(self, child: str, parent: str) -> None:
        self.parents.append((child, parent))

    def hold(self, run_id: str, reason: str) -> dict[str, str]:
        self.events.append(("hold", (run_id, reason)))
        return {"run_id": run_id}

    def release_hold(self, run_id: str, reason: str) -> dict[str, str]:
        return {"run_id": run_id}

    def seal(
        self, run_id: str, record: dict[str, object], work: Path
    ) -> dict[str, object]:
        return {"run_id": run_id, "parents": record["parents"], "work": str(work)}

    def review(
        self, run_id: str, quality: str, *, note: str | None = None
    ) -> dict[str, str | None]:
        return {"run_id": run_id, "quality": quality, "note": note}

    def label(self, run_id: str, action: str, labels: list[str]) -> dict[str, object]:
        return {"run_id": run_id, "action": action, "labels": labels}

    def append_event(
        self, kind: str, subject: str, value: dict[str, object]
    ) -> dict[str, object]:
        self.events.append((kind, (subject, value)))
        return {"kind": kind, "subject": subject, "value": value}


def test_browse_filters_quality_and_emits_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    store = FakeStore(tmp_path)
    monkeypatch.setattr(_cli, "_store", lambda *_: store)

    assert (
        _cli.main(["--storage", str(tmp_path), "--json", "browse", "--quality", "good"])
        == 0
    )

    assert '"run_id": "one"' in capsys.readouterr().out


def _seal(store: Any, run_id: str, record: dict[str, Any] | None = None) -> None:
    work = store.start_work(run_id)
    (work / "outputs").mkdir()
    (work / "outputs" / "result.txt").write_text(run_id)
    store.seal(run_id, record or {}, work)


def test_browse_uses_current_review_and_includes_unreviewed_records(
    tmp_path: Path, capsys
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    _seal(store, "run")

    assert (
        _cli.main(
            ["--storage", str(root), "--json", "browse", "--quality", "unreviewed"]
        )
        == 0
    )
    assert [item["run_id"] for item in json.loads(capsys.readouterr().out)] == ["run"]

    store.review("run", "good")
    store.review("run", "bad")
    assert (
        _cli.main(["--storage", str(root), "--json", "browse", "--quality", "bad"]) == 0
    )
    assert [item["quality"] for item in json.loads(capsys.readouterr().out)] == ["bad"]
    assert (
        _cli.main(["--storage", str(root), "--json", "browse", "--quality", "good"])
        == 0
    )
    assert json.loads(capsys.readouterr().out) == []


def test_browse_weekly_analysis_includes_its_source_parents(
    tmp_path: Path, capsys
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    _seal(store, "source", {"name": "source experiment", "kind": "experiment"})
    work = store.start_work("analysis")
    store.register_parent("analysis", "source")
    (work / "figure.txt").write_text("figure")
    store.seal(
        "analysis",
        {"kind": "analysis", "name": "weekly comparison", "used_in": "weekly"},
        work,
    )

    assert (
        _cli.main(["--storage", str(root), "--json", "browse", "--used-in", "weekly"])
        == 0
    )
    found = {item["run_id"]: item for item in json.loads(capsys.readouterr().out)}
    assert set(found) == {"source", "analysis"}
    assert found["analysis"]["kind"] == "analysis"


def test_browse_exposes_legacy_origin_and_searches_name_and_origin(
    tmp_path: Path, capsys
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    _seal(store, "named", {"name": "melon calibration", "kind": "experiment"})
    legacy = tmp_path / "apple-legacy"
    legacy.mkdir()
    (legacy / "output.dat").write_text("old")
    store.import_legacy(legacy, "apple/2023-baseline", run_id="legacy")

    assert (
        _cli.main(["--storage", str(root), "--json", "browse", "--search", "melon"])
        == 0
    )
    assert [item["run_id"] for item in json.loads(capsys.readouterr().out)] == ["named"]
    assert (
        _cli.main(
            ["--storage", str(root), "--json", "browse", "--search", "2023-baseline"]
        )
        == 0
    )
    found = json.loads(capsys.readouterr().out)
    assert found[0]["run_id"] == "legacy"
    assert found[0]["legacy_origin"] == "apple/2023-baseline"


def test_analysis_save_registers_parents_and_only_selected_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    store = FakeStore(tmp_path)
    monkeypatch.setattr(_cli, "_store", lambda *_: store)
    workspace = tmp_path / "analysis"
    _cli.main(
        [
            "--storage",
            str(tmp_path),
            "analysis",
            "new",
            str(workspace),
            "--source",
            "parent",
        ]
    )
    (workspace / "out").mkdir()
    (workspace / "out" / "figure.png").write_bytes(b"figure")
    (workspace / "RUN.md").write_text("notes")

    assert (
        _cli.main(
            [
                "--storage",
                str(tmp_path),
                "analysis",
                "save",
                str(workspace),
                "--output",
                "out/figure.png",
            ]
        )
        == 0
    )

    assert any(parent == "parent" for _, parent in store.parents)


def test_analysis_save_rejects_invalid_outputs_before_creating_pending_work(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    _seal(store, "source")
    workspace = tmp_path / "analysis"
    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "analysis",
                "new",
                str(workspace),
                "--source",
                "source",
            ]
        )
        == 0
    )

    with pytest.raises(SystemExit, match="2"):
        _cli.main(
            [
                "--storage",
                str(root),
                "analysis",
                "save",
                str(workspace),
                "--output",
                "../outside.txt",
            ]
        )
    assert not list((root / "pending").glob("*.json"))
    assert not list((root / "work").iterdir())


def test_analysis_saves_living_run_notes_as_immutable_revisions(
    tmp_path: Path, capsys
) -> None:
    """A closed workspace may save a later Markdown-only interpretation."""
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    _seal(store, "source", {"name": "original experiment"})
    source_record = store.read_record("source")
    workspace = tmp_path / "analysis"

    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "analysis",
                "new",
                str(workspace),
                "--source",
                "source",
                "--name",
                "weekly notes",
            ]
        )
        == 0
    )
    (workspace / "RUN.md").write_bytes(b"# First finding\n")
    assert _cli.main(["--storage", str(root), "analysis", "save", str(workspace)]) == 0
    first = json.loads((workspace / "analysis.json").read_text())["latest_record"]

    assert _cli.main(["--storage", str(root), "analysis", "close", str(workspace)]) == 0
    assert "analysis:" not in " ".join(store.projection("source")["holds"])
    (workspace / "RUN.md").write_bytes(b"# Revised finding\n")
    assert _cli.main(["--storage", str(root), "analysis", "save", str(workspace)]) == 0
    config = json.loads((workspace / "analysis.json").read_text())
    second = config["latest_record"]

    assert config["name"] == "weekly notes"
    assert config["revision"] == 2
    assert first != second
    record = store.read_record(second)["record"]
    assert record["workspace_id"] == config["workspace_id"]
    assert record["name"] == "weekly notes"
    assert record["revision"] == 2
    assert record["previous_revision"] == first
    assert set(store.read_record(second)["parents"]) == {"source", first}
    assert store.materialize(first, "RUN.md").read_bytes() == b"# First finding\n"
    assert store.materialize(second, "RUN.md").read_bytes() == b"# Revised finding\n"
    assert store.read_record("source") == source_record

    capsys.readouterr()
    assert _cli.main(["--storage", str(root), "--json", "show", "source"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["projection"]["links"][-1] == {
        "analysis_run": second,
        "workspace_id": config["workspace_id"],
        "name": "weekly notes",
        "revision": 2,
        "previous_revision": first,
    }


def test_analysis_failed_seal_does_not_advance_living_note_pointer(
    tmp_path: Path, monkeypatch
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    _seal(store, "source")
    workspace = tmp_path / "analysis"
    _cli.main(
        [
            "--storage",
            str(root),
            "analysis",
            "new",
            str(workspace),
            "--source",
            "source",
            "--name",
            "notes",
        ]
    )
    (workspace / "RUN.md").write_text("draft")
    original = json.loads((workspace / "analysis.json").read_text())

    def fail_seal(*_args: object, **_kwargs: object) -> dict[str, object]:
        message = "seal failed"
        raise RuntimeError(message)

    monkeypatch.setattr(store, "seal", fail_seal)
    monkeypatch.setattr(_cli, "_store", lambda *_: store)
    with pytest.raises(SystemExit, match="2"):
        _cli.main(["--storage", str(root), "analysis", "save", str(workspace)])
    assert json.loads((workspace / "analysis.json").read_text()) == original


def test_remote_failed_browse_is_rejected_without_claiming_import(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    Store(root, machine_id="machine").ensure_initialized("collection")
    with pytest.raises(SystemExit, match="2"):
        _cli.main(
            [
                "--storage",
                str(root),
                "browse",
                "--failed",
                "--remote",
                str(tmp_path / "remote"),
            ]
        )


def test_cli_archive_sync_round_trips_note_and_link_metadata(tmp_path: Path) -> None:
    """Archive/sync carries all ordinary post-hoc control events to a peer."""
    from liblaf.cherries.records import Store

    source_root = tmp_path / "source"
    source = Store(source_root, machine_id="machine-a")
    source.ensure_initialized("collection")
    _seal(source, "run")
    note = tmp_path / "meeting.md"
    note.write_text("reviewed at meeting")
    assert (
        _cli.main(["--storage", str(source_root), "note", "run", "--file", str(note)])
        == 0
    )
    assert (
        _cli.main(
            [
                "--storage",
                str(source_root),
                "link",
                "run",
                "--git",
                "abc123",
            ]
        )
        == 0
    )
    remote = tmp_path / "remote"
    assert (
        _cli.main(
            ["--storage", str(source_root), "archive", "run", "--remote", str(remote)]
        )
        == 0
    )

    target_root = tmp_path / "target"
    target = Store(target_root, machine_id="machine-b")
    target.ensure_initialized("collection")
    assert (
        _cli.main(["--storage", str(target_root), "sync", "--remote", str(remote)]) == 0
    )
    kinds = {
        json.loads(path.read_text())["kind"]
        for path in (target_root / "metadata" / "events").glob("*/*.json")
    }
    assert {"sealed", "note", "link"} <= kinds


def test_archive_evict_removes_only_verified_view_and_honors_keep_local(
    tmp_path: Path,
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    work = store.start_work("run")
    (work / "out.txt").write_text("shared")
    store.seal("run", {}, work)
    store.materialize("run", "out.txt")
    remote = tmp_path / "remote"

    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "archive",
                "run",
                "--remote",
                str(remote),
                "--evict",
            ]
        )
        == 0
    )
    assert not (root / "runs" / "run").exists()
    assert not list((root / "objects" / "sha256").glob("*/*"))

    store.mark("run", keep_local=True)
    with pytest.raises(SystemExit):
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "archive",
                "run",
                "--remote",
                str(remote),
                "--evict",
            ]
        )
    assert not (root / "runs" / "run").exists()


def test_path_creates_and_releases_owned_durable_lease(tmp_path: Path, capsys) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    work = store.start_work("run")
    (work / "report.txt").write_text("report")
    store.seal("run", {}, work)

    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "--json",
                "path",
                "run",
                "report.txt",
            ]
        )
        == 0
    )
    lease = json.loads(capsys.readouterr().out)["lease"]
    assert (root / "leases" / f"{lease}.json").is_file()
    assert "read:" in next(iter(store.projection("run")["holds"]))

    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "path",
                "--release",
                lease,
            ]
        )
        == 0
    )
    assert not (root / "leases" / f"{lease}.json").exists()


def test_path_releases_reader_hold_when_materialization_fails(tmp_path: Path) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    _seal(store, "run")
    asset = store.read_manifest("run")["files"][0]["asset_id"].removeprefix("sha256:")
    (root / "objects" / "sha256" / asset[:2] / asset).unlink()

    with pytest.raises(SystemExit, match="2"):
        _cli.main(["--storage", str(root), "path", "run", "outputs/result.txt"])
    assert store.projection("run")["holds"] == set()
    assert not list((root / "leases").glob("*.json"))


def test_path_rejects_tree_not_declared_by_selected_record(tmp_path: Path) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "only.txt").write_text("tree")
    tree = store.put_tree(bundle)
    _seal(store, "declared", {"bundle": tree})
    _seal(store, "other")

    with pytest.raises(SystemExit, match="2"):
        _cli.main(["--storage", str(root), "path", "other", tree])
    assert store.projection("other")["holds"] == set()


def test_path_and_local_restore_materialize_declared_empty_tree_directory(
    tmp_path: Path, capsys
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    source = tmp_path / "bundle"
    (source / "empty").mkdir(parents=True)
    tree = store.put_tree(source)
    _seal(store, "run", {"bundles": [{"path": "bundle", "asset_id": tree}]})

    assert _cli.main(["--storage", str(root), "path", "run", "bundle"]) == 0
    lease = capsys.readouterr().out.split("lease: ", 1)[1].strip()
    assert (root / "runs" / "run" / "bundle" / "empty").is_dir()
    assert _cli.main(["--storage", str(root), "path", "--release", lease]) == 0

    shutil.rmtree(root / "runs" / "run")
    assert _cli.main(["--storage", str(root), "restore", "run"]) == 0
    assert (root / "runs" / "run" / "bundle" / "empty").is_dir()
    assert store.projection("run")["holds"] == set()


def test_global_flags_are_accepted_after_subcommand(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    store = FakeStore(tmp_path)
    monkeypatch.setattr(_cli, "_store", lambda *_: store)

    assert _cli.main(["browse", "--json", "--storage", str(tmp_path)]) == 0
    assert '"run_id"' in capsys.readouterr().out
    monkeypatch.setattr(
        sys, "argv", ["cherries", "browse", "--json", "--storage", str(tmp_path)]
    )
    assert _cli.main() == 0
    assert '"run_id"' in capsys.readouterr().out


def test_migrated_records_are_searchable_by_source_and_emit_json_arrays(
    tmp_path: Path, capsys
) -> None:
    from liblaf.cherries.records import Store

    store = Store(tmp_path / "store")
    source = tmp_path / "mouthopen"
    source.mkdir()
    (source / "result.txt").write_text("result")
    store.import_legacy(source, "old-exp", run_id="legacy")
    store.append_event(
        "note", "legacy", {"legacy_source": str(source), "name": "mouthopen"}
    )
    assert (
        _cli.main(
            ["browse", "--storage", str(store.root), "--search", "mouthopen", "--json"]
        )
        == 0
    )
    records = json.loads(capsys.readouterr().out)
    assert len(records) == 1
    assert records[0]["name"] == "mouthopen"
    assert records[0]["legacy_source"] == str(source)
    assert records[0]["labels"] == []
    assert records[0]["holds"] == []


def test_read_releases_hold_after_missing_asset(tmp_path: Path) -> None:
    from liblaf.cherries.records import Store

    store = Store(tmp_path / "store")
    work = store.start_work("run")
    (work / "result").write_text("result")
    store.seal("run", {}, work)
    with pytest.raises(SystemExit):
        _cli.main(["--storage", str(store.root), "read", "run", "missing.txt"])
    assert not store.projection("run")["holds"]


def test_local_maintenance_plan_and_apply_are_receipt_bound(
    tmp_path: Path, capsys
) -> None:
    from liblaf.cherries.records import Store

    root = tmp_path / "store"
    store = Store(root, machine_id="machine")
    store.ensure_initialized("collection")
    work = store.start_work("run")
    (work / "result.txt").write_text("result")
    store.seal("run", {}, work)

    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "--json",
                "maintenance",
                "pause",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "--json",
                "discard",
                "run",
                "--plan",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "discard",
                "--apply",
                plan["path"],
            ]
        )
        == 0
    )
    assert (
        _cli.main(
            [
                "--storage",
                str(root),
                "--machine-id",
                "machine",
                "maintenance",
                "resume",
                receipt["token"],
            ]
        )
        == 0
    )


def test_rerun_executes_prepared_script_with_mapping_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_source_capture import make_replay_record

    store, run_id, _ = make_replay_record(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    assert (
        _cli.main(
            [
                "--storage",
                str(store.root),
                "--machine-id",
                "test-machine",
                "rerun",
                run_id,
                "--workspace",
                str(workspace),
            ]
        )
        == 0
    )
    replay = json.loads((workspace / "replay.json").read_text())
    assert Path(replay["input_mapping"]).is_file()
    assert not store.projection(run_id)["holds"]

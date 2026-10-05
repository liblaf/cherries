# Copyright (c) 2026 liblaf
# ruff: noqa: SLF001
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from liblaf.cherries import _cli
from liblaf.cherries.records import Store


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "store", machine_id="machine")
    store.ensure_initialized("collection")
    for run_id in ("source-a", "source-b", "source-c"):
        work = store.start_work(run_id)
        (work / "result.txt").write_text(run_id)
        store.seal(run_id, {"kind": "experiment"}, work)
    return store


def cli(store: Store, *args: str) -> int:
    return _cli.main(["--storage", str(store.root), *args])


def test_weekly_filter_combines_with_source_quality(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = make_store(tmp_path)
    store.review("source-a", "good")
    work = store.start_work("weekly-analysis")
    store.register_parent("weekly-analysis", "source-a")
    store.seal("weekly-analysis", {"used_in": "weekly"}, work)

    assert (
        cli(store, "--json", "browse", "--used-in", "weekly", "--quality", "good") == 0
    )
    assert [row["run_id"] for row in json.loads(capsys.readouterr().out)] == [
        "source-a"
    ]


def test_path_reopens_closed_workspace_source_hold(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    workspace = tmp_path / "analysis"
    cli(store, "analysis", "new", str(workspace), "--source", "source-a")
    cli(store, "analysis", "close", str(workspace))
    assert not store.projection("source-a")["holds"]

    assert (
        cli(store, "path", "source-a", "result.txt", "--workspace", str(workspace)) == 0
    )
    config = json.loads((workspace / "analysis.json").read_text())
    assert f"analysis:{config['workspace_id']}" in store.projection("source-a")["holds"]


def test_path_retains_reader_when_workspace_closes_during_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    workspace = tmp_path / "analysis"
    cli(store, "analysis", "new", str(workspace), "--source", "source-a")
    original_bind = _cli._bind_analysis_source
    eviction_attempts: list[dict[str, Any]] = []

    def close_after_binding(
        selected_store: Store, folder: Path, run_id: str
    ) -> dict[str, Any]:
        config = original_bind(selected_store, folder, run_id)
        selected_store.release_hold(run_id, f"analysis:{config['workspace_id']}")
        eviction_attempts.append(
            selected_store.evict_local(run_id, remote_verified=True)
        )
        return config

    monkeypatch.setattr(_cli, "_bind_analysis_source", close_after_binding)
    assert (
        cli(store, "path", "source-a", "result.txt", "--workspace", str(workspace)) == 0
    )
    assert not eviction_attempts[0]["allowed"]
    assert not store.projection("source-a")["holds"]


def test_failed_analysis_new_releases_holds_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    workspace = tmp_path / "analysis"
    original_write = _cli._write_analysis

    def fail_write(*_args: object) -> None:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(_cli, "_write_analysis", fail_write)
    with pytest.raises(SystemExit, match="2"):
        cli(store, "analysis", "new", str(workspace), "--source", "source-a")
    assert not store.projection("source-a")["holds"]
    assert not workspace.exists()
    monkeypatch.setattr(_cli, "_write_analysis", original_write)
    assert cli(store, "analysis", "new", str(workspace), "--source", "source-a") == 0


def test_source_remove_write_failure_preserves_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    workspace = tmp_path / "analysis"
    cli(store, "analysis", "new", str(workspace), "--source", "source-a")
    original = (workspace / "analysis.json").read_bytes()

    def fail_write(*_args: object) -> None:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr(_cli, "_write_analysis", fail_write)
    with pytest.raises(SystemExit, match="2"):
        cli(store, "analysis", "source", str(workspace), "remove", "source-a")
    assert (workspace / "analysis.json").read_bytes() == original
    assert store.projection("source-a")["holds"]


def test_concurrent_source_adds_keep_both_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    workspace = tmp_path / "analysis"
    cli(store, "analysis", "new", str(workspace), "--source", "source-a")
    original_write = _cli._write_analysis
    first_writing = Event()
    second_finished = Event()

    def ordered_write(folder: Path, config: dict[str, Any]) -> None:
        if "source-b" in config["sources"] and "source-c" not in config["sources"]:
            first_writing.set()
            second_finished.wait(timeout=0.5)
        original_write(folder, config)

    monkeypatch.setattr(_cli, "_write_analysis", ordered_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            cli, store, "analysis", "source", str(workspace), "add", "source-b"
        )
        assert first_writing.wait(timeout=5)
        second = pool.submit(
            cli, store, "analysis", "source", str(workspace), "add", "source-c"
        )
        second.add_done_callback(lambda _future: second_finished.set())
        assert first.result(timeout=5) == 0
        assert second.result(timeout=5) == 0
    config = json.loads((workspace / "analysis.json").read_text())
    assert set(config["sources"]) == {"source-a", "source-b", "source-c"}


def test_failed_analysis_save_cleans_unsealed_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    workspace = tmp_path / "analysis"
    cli(store, "analysis", "new", str(workspace), "--source", "source-a")

    def fail_seal(*_args: object, **_kwargs: object) -> None:
        message = "seal failed"
        raise RuntimeError(message)

    monkeypatch.setattr(Store, "seal", fail_seal)
    with pytest.raises(SystemExit, match="2"):
        cli(store, "analysis", "save", str(workspace))
    assert not list((store.root / "pending").glob("*.json"))
    assert not list((store.root / "work").iterdir())
    assert "latest_record" not in json.loads((workspace / "analysis.json").read_text())


def test_rerun_receipt_write_failure_releases_reader_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from liblaf.cherries import _capture

    store = make_store(tmp_path)
    workspace = tmp_path / "replay"
    reason = "replay:test"
    original_write = Path.write_text

    def prepare(_store: Store, _run_id: str, folder: Path) -> dict[str, str]:
        folder.mkdir()
        _store.hold("source-a", reason)
        return {"run_id": "source-a", "reader_hold": reason}

    def fail_receipt(path: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if path == workspace / "replay.json":
            message = "disk full"
            raise OSError(message)
        return original_write(path, data, *args, **kwargs)

    monkeypatch.setattr(_capture, "prepare_replay", prepare)
    monkeypatch.setattr(Path, "write_text", fail_receipt)
    with pytest.raises(SystemExit, match="2"):
        cli(store, "rerun", "source-a", "--prepare-only", "--workspace", str(workspace))
    assert not store.projection("source-a")["holds"]

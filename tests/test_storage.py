# Copyright (c) 2026 liblaf
"""Local storage, manifest verification, daily layout, and artifact-lineage pruning."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries._io import run_relative_path, write_yaml
from liblaf.cherries._storage import LocalStore, resolve_lineage


def _make_run(
    store: LocalStore,
    run_id: str,
    *,
    start_time: str = "2026-11-15 08:00:00+08:00",
    tags: list[str] | None = None,
    inputs: dict[str, bytes] | None = None,
    outputs: dict[str, bytes] | None = None,
    figs: dict[str, bytes] | None = None,
    unfinished: bool = False,
) -> Path:
    suffix = ".tmp" if unfinished else ""
    directory = store.runs_dir / run_relative_path(run_id + suffix, start_time)
    (directory / "src").mkdir(parents=True)
    (directory / "src/10-run.py").write_text("pass\n")
    (directory / "run.log").write_text("ok\n")
    artifacts: dict[str, list[dict[str, Any]]] = {
        "inputs": [],
        "outputs": [],
        "figs": [],
    }
    for role, files in (
        ("inputs", inputs or {}),
        ("outputs", outputs or {}),
        ("figs", figs or {}),
    ):
        for name, payload in sorted(files.items()):
            target = directory / role / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            artifacts[role].append(
                {
                    "name": name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            )
    write_yaml(
        directory / "run.yaml",
        {
            "project-id": store.project_id,
            "run-id": run_id,
            "run-name": run_id,
            "start-time": start_time,
            "end-time": None if unfinished else start_time,
            "tags": list(tags or []),
            "params": {},
            "commit": None if unfinished else "a" * 40,
            "metadata": {},
            "artifacts": artifacts,
        },
    )
    return directory


def test_local_edit_add_and_verify(repo: Path, saved: Path, tmp_path: Path) -> None:
    local = LocalStore(repo)
    run = local.get(saved.name)
    times = {key: run.metadata[key] for key in ("start-time", "end-time")}
    run.edit(
        name="checked",
        description="verified",
        add_tags=["selected"],
        metadata={"n": 1},
    )
    assert {key: run.metadata[key] for key in times} == times
    assert run.metadata["run-name"] == "checked"
    assert run.metadata["description"] == "verified"
    assert "selected" in run.metadata["tags"]

    attachment = tmp_path / "attachment"
    (attachment / "nested/empty").mkdir(parents=True)
    (attachment / "nested/file.txt").write_text("attachment")
    run.add(attachment, "assets/attachment")
    assert (run.directory / "assets/attachment/nested/file.txt").read_text() == (
        "attachment"
    )
    assert not (run.directory / "assets/attachment/nested/empty").exists()

    figures = tmp_path / "figures"
    (figures / "nested/empty").mkdir(parents=True)
    (figures / "nested/a.lfs").write_bytes(b"literal suffix")
    (figures / "nested/zero").write_bytes(b"")
    run.add(figures, "figs/bundle")
    assert (run.directory / "figs/bundle/nested/a.lfs").read_bytes() == (
        b"literal suffix"
    )
    assert (run.directory / "figs/bundle/nested/zero").read_bytes() == b""
    assert not (run.directory / "figs/bundle/nested/empty").exists()

    # Extra freeform notes in the run directory are allowed.
    (run.directory / "notes.txt").write_text("freeform note\n")

    with pytest.raises(ValueError, match="fixed"):
        run.add(attachment / "nested/file.txt", "outputs/result.txt")
    run.verify()


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "../escape", "sha256": "a" * 64, "size": 1},
        {"name": "/absolute", "sha256": "a" * 64, "size": 1},
        {"name": "nested//file", "sha256": "a" * 64, "size": 1},
        {"name": "file", "sha256": "A" * 64, "size": 1},
        {"name": "file", "sha256": "a" * 64, "size": -1},
        {"name": "file", "sha256": "a" * 64, "size": True},
        {"name": "file", "sha256": "a" * 64, "size": 1, "extra": 2},
    ],
)
def test_corrupt_manifest_fails_verify(
    repo: Path, saved: Path, entry: dict[str, Any]
) -> None:
    record = LocalStore(repo).get(saved.name)
    data = record.metadata
    data["artifacts"]["outputs"] = [entry]
    write_yaml(record.directory / "run.yaml", data)
    with pytest.raises(ValueError):  # noqa: PT011 - Pydantic ValidationError
        record.verify()


@pytest.mark.parametrize("change", ["missing", "changed", "unlisted", "role-file"])
def test_verify_checks_local_manifest_against_real_files(
    repo: Path, saved: Path, change: str
) -> None:
    if change == "missing":
        (saved / "outputs/result.txt").unlink()
    elif change == "changed":
        (saved / "outputs/result.txt").write_text("changed")
    elif change == "unlisted":
        (saved / "outputs/unlisted").write_text("not registered")
    else:
        shutil.rmtree(saved / "outputs")
        (saved / "outputs").write_text("not a role directory")
    with pytest.raises(ValueError, match=r"artifact|Artifact"):
        LocalStore(repo).get(saved.name).verify()


def test_verify_checks_log_and_date_mismatch_before_payloads(
    repo: Path, saved: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = LocalStore(repo).get(saved.name)
    (saved / "run.log").unlink()
    with pytest.raises(ValueError, match=r"Missing run\.log"):
        record.verify()
    (saved / "run.log").write_text("ok\n")

    data = record.metadata
    data["start-time"] = "1999-12-31 23:59:59-12:00"
    write_yaml(saved / "run.yaml", data)
    original_open = Path.open

    def no_payload_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        assert not any(
            saved / role in path.parents for role in ("inputs", "outputs", "figs")
        )
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_payload_open)
    with pytest.raises(ValueError, match="start-time"):
        record.verify()


def test_remove_prunes_only_empty_dates_and_stops_at_cherries_root(repo: Path) -> None:
    store = LocalStore(repo)
    first = _make_run(store, "first", start_time="2026-01-01 00:00:00+00:00")
    same_day = _make_run(store, "same-day", start_time="2026-01-01 01:00:00+00:00")
    next_day = _make_run(store, "next-day", start_time="2026-01-02 00:00:00+00:00")
    next_month = _make_run(store, "next-month", start_time="2026-02-01 00:00:00+00:00")
    unrelated = store.root / "notes.txt"
    unrelated.write_text("keep")

    store.get(first).remove()
    assert same_day.is_dir()
    store.get(same_day).remove()
    assert not first.parent.exists()
    assert next_day.is_dir()
    store.get(next_day).remove()
    assert not (store.runs_dir / "2026/01").exists()
    assert next_month.is_dir()
    unrelated.unlink()
    store.get(next_month).remove()
    assert not store.runs_dir.exists()
    assert store.root.is_dir()


def test_lineage_and_prune_follow_artifact_chain_and_ignore_empty_files(
    repo: Path,
) -> None:
    store = LocalStore(repo)
    mesh = b"mesh bytes v1"
    sim = b"simulation bytes v1"
    fig = b"paper figure bytes"
    garbage = b"discarded branch bytes"

    _make_run(store, "run-a", outputs={"mesh.vtu": mesh})
    _make_run(store, "run-b", inputs={"mesh.vtu": mesh}, outputs={"sim.vtu": sim})
    _make_run(
        store,
        "run-c",
        tags=["selected"],
        inputs={"sim.vtu": sim, "empty.txt": b""},
        figs={"fig1.png": fig},
    )
    _make_run(store, "run-dead", outputs={"empty.txt": b"", "trash.vtu": garbage})
    pending = _make_run(store, "run-wip", unfinished=True)

    assert [m["run-id"] for m in store.lineage(tags=["selected"])] == [
        "run-c",
        "run-b",
        "run-a",
    ]
    assert store.lineage(tags=["nonexistent"]) == []
    with pytest.raises(ValueError, match="No runs matched"):
        store.prune(tags=["nonexistent"])
    assert store.find("run-dead") is not None

    dry = store.prune(tags=["selected"], dry_run=True)
    assert dry == {"keep": ["run-c", "run-b", "run-a"], "remove": ["run-dead"]}
    assert store.find("run-dead") is not None
    assert pending.exists()

    assert store.prune(tags=["selected"]) == dry
    assert store.find("run-dead") is None
    assert sorted(r.id for r in store.runs()) == ["run-a", "run-b", "run-c"]
    assert pending.exists()

    assert store.prune(tags=["selected"], unfinished=True) == {
        "keep": ["run-c", "run-b", "run-a"],
        "remove": ["run-wip.tmp"],
    }
    assert not pending.exists()


def test_resolve_lineage_rejects_unknown_seed() -> None:
    with pytest.raises(FileNotFoundError, match="missing"):
        resolve_lineage({}, ["missing"])


def test_edit_and_add_reject_unfinished_runs_and_validate_before_copy(
    repo: Path, saved: Path, tmp_path: Path
) -> None:
    store = LocalStore(repo)
    pending = _make_run(store, "wip", unfinished=True)
    fig = tmp_path / "plot.png"
    fig.write_bytes(b"img")
    with pytest.raises(ValueError, match="unfinished"):
        store.get(pending).edit(description="nope")
    with pytest.raises(ValueError, match="unfinished"):
        store.get(pending).add(fig, "figs/plot.png")
    assert not (pending / "figs/plot.png").exists()

    # Bare directory targets, directory reports, and fig conflicts fail cleanly.
    run = store.get(saved.name)
    for bad_target in ("figs", "assets", "reports"):
        with pytest.raises(ValueError, match="invalid"):
            run.add(fig, bad_target)
    with pytest.raises(ValueError, match="directory"):
        run.add(tmp_path, "README.md")
    with pytest.raises(ValueError, match="conflict"):
        run.add(fig, "figs/loss.png/nested.png")
    assert (saved / "figs/loss.png").read_bytes() == b"figure"


def test_local_get_supports_ids_unfinished_ids_paths_and_detects_ambiguity(
    repo: Path, saved: Path
) -> None:
    local = LocalStore(repo)
    assert local.get(saved.name).directory == saved
    assert local.get(saved).directory == saved
    pending = _make_run(
        local,
        "unfinished",
        start_time="2024-02-29 23:59:59+08:00",
        unfinished=True,
    )
    assert local.get("unfinished.tmp").directory == pending
    assert local.get(pending).directory == pending
    assert {run.directory for run in local.runs(unfinished=True)} == {pending}
    assert {run.directory for run in local.runs()} == {saved}

    duplicate = local.runs_dir / "2020/02/29" / saved.name
    shutil.copytree(saved, duplicate)
    data = local.show(duplicate)
    data.update(
        {
            "start-time": "2020-02-29 00:00:00+00:00",
            "end-time": "2020-02-29 00:00:00+00:00",
        }
    )
    write_yaml(duplicate / "run.yaml", data)
    with pytest.raises(ValueError, match="Ambiguous run ID"):
        local.get(saved.name)

    with pytest.raises(FileNotFoundError):
        local.get(repo)


def test_local_list_metadata_filters_limits_and_rejects_corrupt_yaml(
    repo: Path, saved: Path
) -> None:
    local = LocalStore(repo)
    assert [m["run-id"] for m in local.list_metadata(tags=["baseline"])] == [saved.name]
    assert [m["run-id"] for m in local.list_metadata(search="initial")] == [saved.name]
    assert local.list_metadata(limit=0) == []
    with pytest.raises(ValueError, match="non-negative"):
        local.list_metadata(limit=-1)

    (saved / "run.yaml").write_text("", encoding="utf-8")
    with pytest.raises(TypeError, match="YAML mapping"):
        local.get(saved).verify()

    # RunMeta requires canonical hyphenated keys and explicit commit field.
    bad = local.get(_make_run(local, "bad-meta", unfinished=True))
    data = bad.metadata
    del data["commit"]
    write_yaml(bad.directory / "run.yaml", data)
    with pytest.raises(ValueError):  # noqa: PT011 - Pydantic ValidationError
        bad.verify()

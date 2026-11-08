# Copyright (c) 2026 liblaf
# ruff: noqa: EM101, SLF001, TRY003
# Fault injection deliberately targets private filesystem publication boundaries.
"""Behavioral contracts for the filesystem project/run store."""

from __future__ import annotations

import dataclasses
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest

from liblaf.cherries.store import _store
from liblaf.cherries.store._io import (
    ConflictError,
    IntegrityError,
    NotFoundError,
    read_yaml,
    write_yaml,
)
from liblaf.cherries.store._store import DirectoryRef, DraftRun, Store, pointer_bytes


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store.create(tmp_path / "store", cache_root=tmp_path / "cache")


def saved(
    store: Store,
    project: str = "p",
    *,
    name: str = "run",
    data: bytes = b"payload",
    suffix: str = "vtu",
    **metadata: Any,
) -> Any:
    draft = store.projects.add(project).runs.create(name=name, **metadata)
    draft.output("result." + suffix).write_bytes(data)
    draft.save(git={})
    return draft.project.runs.get(draft.id)


def test_explicit_format_open_never_initializes_or_cleans(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "collection.json").write_text("{}")
    with pytest.raises(IntegrityError, match="legacy"):
        Store.open(legacy)
    with pytest.raises(ConflictError, match="empty"):
        Store.create(legacy)
    assert sorted(path.name for path in legacy.iterdir()) == ["collection.json"]
    with pytest.raises(NotFoundError):
        Store.open(tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


def test_uuid7_and_explicit_import_identity(store: Store) -> None:
    project = store.projects.add("p")
    a = project.runs.create(name="a")
    b = project.runs.create(name="b")
    assert uuid.UUID(a.id).version == 7
    assert a.id < b.id
    explicit = "a1234567-1234-1234-1234-123456789abc"
    imported = project.runs.create(name="import", id=explicit)
    assert imported.id == explicit
    with pytest.raises(ConflictError):
        project.runs.create(name="duplicate", id=explicit)
    reopened = Store.open(store.root, cache_root=store.cache_root)
    assert isinstance(reopened.projects.get("p").runs.get(a.id), DraftRun)


def test_global_cas_suffix_last_put_and_old_pointer_reads(store: Store) -> None:
    first = saved(store, "a", suffix="VTU")
    ref = first.file("outputs/result.VTU").ref()
    second = saved(store, "b", suffix="npz")
    objects = _store.files(store.root / "objects")
    assert len(objects) == 1
    assert objects[0].suffix == ".npz"
    assert first.file("outputs/result.VTU").materialize().read_bytes() == b"payload"
    assert second.file("outputs/result.npz").ref().oid == ref.oid
    assert _store.files(store.root / "objects")[0].suffix == ".npz"


def test_pointer_import_is_payload_and_missing_object_is_error(
    store: Store, tmp_path: Path
) -> None:
    parent = saved(store)
    ref = parent.file("outputs/result.vtu").ref()
    pointer = tmp_path / "renamed.txt"
    pointer.write_bytes(pointer_bytes(ref.oid, ref.size))
    draft = parent.project.runs.create(name="copy")
    draft.add_file(pointer, path="outputs/copied.bin")
    assert (draft.directory / "outputs/copied.bin").read_bytes() == b"payload"
    draft.save(git={})
    assert (
        draft.project.runs.get(draft.id).file("outputs/copied.bin").ref().oid == ref.oid
    )
    pointer.write_bytes(pointer_bytes("sha256:" + "f" * 64, 0))
    with pytest.raises(NotFoundError):
        parent.project.runs.create(name="missing").add_file(pointer, path="outputs/x")


def test_zero_byte_payload_has_explicit_three_line_pointer(store: Store) -> None:
    run = saved(store, data=b"")
    path = run.directory / "outputs/result.vtu.lfs"
    assert path.read_text().endswith("size 0\n")
    assert run.file("outputs/result.vtu").materialize().read_bytes() == b""


def test_bound_input_survives_parent_replacement_and_suffix_stays(
    store: Store, tmp_path: Path
) -> None:
    parent = saved(store)
    source = parent.file("outputs/result.vtu").ref()
    child = store.projects.add("view").runs.create(name="render")
    local = child.input(source, name="mesh.npz")
    assert local.read_bytes() == b"payload"
    assert store.object_path(source.oid).suffix == ".vtu"
    child.save(git={})
    assert store.object_path(source.oid).suffix == ".vtu"
    replacement = tmp_path / "replacement.vtu"
    replacement.write_bytes(b"new")
    with parent.edit() as edit:
        edit.add_file(replacement, path="outputs/result.vtu")
    archived_child = child.project.runs.get(child.id)
    assert (
        archived_child.file("inputs/mesh.npz").materialize().read_bytes() == b"payload"
    )
    assert parent.file("outputs/result.vtu").materialize().read_bytes() == b"new"
    with pytest.raises(ConflictError, match="consumed"), archived_child.edit() as edit:
        edit.remove_file("inputs/mesh.npz")
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.size = 5


def test_changed_consumed_input_preserves_unpublished_evidence(store: Store) -> None:
    parent = saved(store)
    draft = parent.project.runs.create(name="child")
    bound = draft.input(parent.file("outputs/result.vtu").ref())
    bound.write_bytes(b"modified")
    with pytest.raises(IntegrityError, match="consumed") as caught:
        draft.save(git={})
    assert not caught.value.result.saved
    assert draft.directory.name.endswith(".tmp")
    assert bound.read_bytes() == b"modified"
    reopened = Store.open(store.root, cache_root=store.cache_root)
    assert reopened.recover().retained == [str(draft.directory)]
    assert bound.exists()


def test_required_outputs_failure_and_failed_diagnostics_are_distinct(
    store: Store,
) -> None:
    draft = store.projects.add("p").runs.create(name="missing")
    draft.output("required.npz")
    with pytest.raises(IntegrityError, match="required"):
        draft.save(status="succeeded", git={})
    store.recover()
    result = draft.save(status="failed", git={}, execution={"exit_code": 7})
    assert result.saved
    assert result.execution_status == "failed"
    assert result.exit_code == 7
    assert draft.metadata["missing_outputs"] == ["outputs/required.npz"]


def test_reports_assets_export_and_cache_are_independent(
    store: Store, tmp_path: Path
) -> None:
    run = saved(store)
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    with run.edit() as edit:
        edit.asset("image.png", source=image)
        edit.report("README.html").write_text('<img src="assets/image.png">')
    copied = tmp_path / "report"
    shutil.copytree(run.directory, copied)
    assert (copied / "assets/image.png").read_bytes() == b"image"
    cache = run.file("outputs/result.vtu").materialize()
    cache.write_bytes(b"external change")
    assert run.file("outputs/result.vtu").materialize().read_bytes() == b"payload"
    exported = run.export(tmp_path / "export", with_data=True)
    assert (exported / "outputs/result.vtu").read_bytes() == b"payload"
    assert not (exported / "outputs/result.vtu.lfs").exists()
    with pytest.raises(IntegrityError, match="missing"), run.edit() as edit:
        edit.remove_file("assets/image.png")
    assert (run.directory / "assets/image.png").exists()


def test_literal_pointer_in_inline_evidence_is_not_data(store: Store) -> None:
    run = saved(store)
    with run.edit() as edit:
        edit.report("README.md").write_bytes(pointer_bytes("sha256:" + "f" * 64, 123))
    item = run.file("README.md")
    assert not item.is_pointer
    assert item.materialize().read_bytes().startswith(b"version")
    assert run.validate().ok
    assert store.gc().reclaimable_bytes == 0


def test_edit_crash_journal_recovers_and_protects_other_mutations(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = saved(store)
    copy_file = _store._copy
    triggered = False

    def interrupted(source: Path, target: Path) -> None:
        nonlocal triggered
        if target == run.directory / "README.md" and not triggered:
            triggered = True
            raise OSError("interrupted edit installation")
        copy_file(source, target)

    monkeypatch.setattr(_store, "_copy", interrupted)
    with pytest.raises(OSError, match="interrupted"), run.edit() as edit:  # noqa: PT012 - failure is injected during context exit
        edit.tags.add("reviewed")
        edit.report("README.md").write_text("# Complete\n")
    assert store._transactions()
    with pytest.raises(ConflictError, match="recovery"):
        store.projects.add("new")
    with pytest.raises(ConflictError, match="recovery"):
        store.gc(dry_run=False)
    assert store.recover().ok
    assert (run.directory / "README.md").read_text() == "# Complete\n"
    assert run.metadata["tags"] == ["reviewed"]
    assert not store._transactions()


def test_execution_metadata_is_immutable_and_unknown_extensions_survive(
    store: Store,
) -> None:
    run = saved(store, parameters={"steps": 10})
    with run.edit() as edit:
        edit.metadata["extensions"]["custom"] = {"answer": 42}
        edit.tags.add("ok")
    with pytest.raises(ConflictError, match="execution"), run.edit() as edit:
        edit.metadata["parameters"]["steps"] = 20
    assert run.metadata["parameters"] == {"steps": 10}
    assert run.metadata["extensions"]["custom"] == {"answer": 42}


def test_query_rebuild_corrupt_cache_and_safe_dsl(store: Store) -> None:
    a = saved(store, "a", name="match", tags=["one", "two"], parameters={"steps": 20})
    draft = store.projects.get("a").runs.create(
        name="other", tags=["one"], parameters={"steps": 2}
    )
    draft.save(git={}, metrics={"loss": {"last": "NaN", "count": 1}})
    metadata = a.metadata
    metadata["metrics"] = {"loss": {"last": 0.001, "count": 10}}
    write_yaml(a.directory / "run.yaml", metadata)
    assert [
        row.id
        for row in a.project.runs.query(
            tags=["one", "two"],
            where='parameters["steps"] >= 10 and metrics["loss"].last < 0.01',
            refresh=True,
        )
    ] == [a.id]
    before = a.fingerprint
    store.index.path.write_bytes(b"broken SQLite cache")
    assert [row.id for row in store.query(where='name == "match"')] == [a.id]
    store.index.path.unlink()
    assert store.index.rebuild().runs == 2
    assert a.fingerprint == before
    for expression in (
        '__import__("os").system("false")',
        "metrics.__class__",
        "unknown == 1",
    ):
        with pytest.raises(IntegrityError):
            store.query(where=expression)


def test_delete_source_closure_and_cross_project_dedup(store: Store) -> None:
    parent = saved(store, "a")
    child = store.projects.add("b").runs.create(name="child")
    child.input(parent.file("outputs/result.vtu").ref())
    child.save(git={})
    with pytest.raises(ConflictError, match="depends"):
        parent.project.runs.delete([parent.id], dry_run=False)
    plan = store.delete([("a", parent.id), ("b", child.id)])
    assert plan.exclusive_cas_bytes == len(b"payload")
    assert parent.directory.exists()
    assert child.directory.exists()
    receipt = store.delete([("a", parent.id), ("b", child.id)], dry_run=False)
    assert receipt.released_bytes > 0
    assert store.gc().reclaimable_bytes == len(b"payload")
    assert store.gc(dry_run=False).reclaimed_bytes == len(b"payload")
    assert not _store.files(store.root / "objects")


def test_gc_uses_authority_and_stops_for_draft_or_unknown_material(
    store: Store,
) -> None:
    run = saved(store)
    store.index.path.unlink()
    assert not store.gc().objects
    unknown = store.root / "preservation"
    unknown.mkdir()
    with pytest.raises(ConflictError, match="unknown"):
        store.gc(dry_run=False)
    unknown.rmdir()
    run.project.runs.create(name="prepared")
    with pytest.raises(ConflictError, match="unpublished"):
        store.gc()


def test_copy_full_ancestry_conflicts_and_explicit_mutable_replace(
    store: Store, tmp_path: Path
) -> None:
    parent = saved(store, "a")
    child = store.projects.add("b").runs.create(name="child")
    child.input(parent.file("outputs/result.vtu").ref())
    child.save(git={})
    child_run = child.project.runs.get(child.id)
    target = Store.create(tmp_path / "target", cache_root=tmp_path / "target-cache")
    receipt = child_run.copy_to(target)
    assert receipt.ok
    assert len(receipt.runs) == 2
    target_child = target.projects.get("b").runs.get(child.id)
    assert (
        target_child.file("inputs/result.vtu").materialize().read_bytes() == b"payload"
    )
    expected = target_child.fingerprint
    with child_run.edit() as edit:
        edit.report("README.md").write_text("# Updated")
    with pytest.raises(ConflictError, match="mutable"):
        child_run.copy_to(target)
    with pytest.raises(ConflictError):
        child_run.copy_to(target, replace=True, expected_target="wrong")
    assert child_run.copy_to(target, replace=True, expected_target=expected).ok
    assert (target_child.directory / "README.md").read_text() == "# Updated"
    source_meta = child_run.metadata
    source_meta["parameters"]["changed"] = True
    write_yaml(child_run.directory / "run.yaml", source_meta)
    with pytest.raises(ConflictError, match="execution"):
        child_run.copy_to(
            target, replace=True, expected_target=target_child.fingerprint
        )


def test_posthoc_source_attachment_preserves_provenance_not_consumption(
    store: Store,
) -> None:
    parent = saved(store)
    child = saved(store, "b")
    store.bind_input(
        child,
        parent.file("outputs/result.vtu").ref(),
        "inputs/later.vtu",
        consumed=False,
    )
    assert not child.metadata["input_bindings"]
    assert child.metadata["attachments"][0]["source"]["run"] == parent.id
    with pytest.raises(ConflictError, match="depends"):
        parent.project.runs.delete(parent.id)


def test_publication_durability_failure_is_recoverable(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = store.projects.add("p").runs.create(name="publication")
    draft.output("x").write_text("x")
    sync = _store.fsync_dir
    final = draft.directory.with_name(draft.id)

    def fail_confirmation(path: Path) -> None:
        if path == final.parent and final.exists():
            raise OSError("confirmation failed")
        sync(path)

    monkeypatch.setattr(_store, "fsync_dir", fail_confirmation)
    result = draft.save(git={})
    assert result.published
    assert not result.saved
    assert result.durability == "unconfirmed"
    assert final.is_dir()
    assert store._transactions()
    monkeypatch.setattr(_store, "fsync_dir", sync)
    assert store.recover().ok
    assert not store._transactions()


def test_companion_group_restores_topology_and_empty_directories(
    store: Store, tmp_path: Path
) -> None:
    draft = store.projects.add("p").runs.create(name="series")
    draft.output("frames.series").write_text('{"files":[{"name":"frames/000.vtu"}]}')
    draft.output("frames/000.vtu").write_bytes(b"frame")
    draft.group(
        "outputs/frames.series",
        files=["outputs/frames/000.vtu"],
        empty_directories=["outputs/frames/empty"],
    )
    draft.save(git={})
    run = draft.project.runs.get(draft.id)
    path = run.file("outputs/frames.series").materialize()
    assert (path.parent / "frames/000.vtu").read_bytes() == b"frame"
    assert (path.parent / "frames/empty").is_dir()
    copied = run.file("outputs/frames.series").copy_to(
        tmp_path / "restored" / "frames.series"
    )
    assert (copied.parent / "frames/000.vtu").read_bytes() == b"frame"


def test_batch_copy_preflights_all_identity_conflicts(
    store: Store, tmp_path: Path
) -> None:
    first = saved(store, name="first")
    second = saved(store, name="second", parameters={"steps": 1})
    target = Store.create(tmp_path / "target", cache_root=tmp_path / "target-cache")
    second.copy_to(target)
    metadata = second.metadata
    metadata["parameters"]["steps"] = 2
    write_yaml(second.directory / "run.yaml", metadata)
    with pytest.raises(ConflictError, match="execution"):
        store.copy_runs([first, second], target)
    with pytest.raises(NotFoundError):
        target.projects.get("p").runs.get(first.id)


def test_interrupted_copy_replacement_recovers_staged_publication(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = saved(store)
    target = Store.create(tmp_path / "target", cache_root=tmp_path / "target-cache")
    run.copy_to(target)
    target_run = target.projects.get("p").runs.get(run.id)
    expected = target_run.fingerprint
    with run.edit() as edit:
        edit.report("README.md").write_text("replacement")
    replace = Path.replace
    interrupted = False

    def fail_after_old_moved(path: Path, destination: Path) -> Path:
        nonlocal interrupted
        if path.name == run.id + ".tmp" and not interrupted:
            interrupted = True
            raise OSError("copy rename interrupted")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_after_old_moved)
    with pytest.raises(OSError, match="interrupted"):
        run.copy_to(target, replace=True, expected_target=expected)
    assert not target_run.directory.exists()
    assert target.recover().ok
    assert (target_run.directory / "README.md").read_text() == "replacement"
    assert not target._transactions()


def test_local_directory_input_binds_members_before_return_and_preserves_empty_dirs(
    store: Store, tmp_path: Path
) -> None:
    source = tmp_path / "dataset"
    (source / "nested" / "empty").mkdir(parents=True)
    (source / "a.bin").write_bytes(b"a")
    (source / "nested" / "b.bin").write_bytes(b"b")
    draft = store.projects.add("p").runs.create(name="directory input")
    directory = draft.input(source)
    metadata = read_yaml(draft.directory / "run.yaml")
    bindings = metadata["input_bindings"]
    assert {item["input"] for item in bindings} == {
        "inputs/dataset/a.bin",
        "inputs/dataset/nested/b.bin",
    }
    assert all(item["consumed"] for item in bindings)
    assert all(
        store.object_path(item["oid"], size=item["size"]).is_file() for item in bindings
    )
    assert (directory / "nested/empty").is_dir()
    (source / "a.bin").write_bytes(b"later source edit")
    assert (directory / "a.bin").read_bytes() == b"a"
    draft.save(git={})
    run = draft.project.runs.get(draft.id)
    result = run.file("inputs/dataset").materialize()
    assert (result / "a.bin").read_bytes() == b"a"
    assert (result / "nested/b.bin").read_bytes() == b"b"
    assert (result / "nested/empty").is_dir()


@pytest.mark.parametrize(
    "change", ["extra-file", "missing-file", "extra-directory", "missing-directory"]
)
def test_directory_input_topology_is_frozen_during_execution(
    store: Store, tmp_path: Path, change: str
) -> None:
    source = tmp_path / "dataset"
    (source / "empty").mkdir(parents=True)
    (source / "value.bin").write_bytes(b"value")
    draft = store.projects.add("p").runs.create(name="unchanged input required")
    directory = draft.input(source)
    if change == "extra-file":
        (directory / "extra.bin").write_bytes(b"extra")
    elif change == "missing-file":
        (directory / "value.bin").unlink()
    elif change == "extra-directory":
        (directory / "new-empty").mkdir()
    else:
        (directory / "empty").rmdir()
    with pytest.raises((IntegrityError, NotFoundError), match=r"input|file not found"):
        draft.save(git={})
    assert draft.directory.name.endswith(".tmp")
    assert draft.directory.exists()


def test_directory_reference_pins_each_member_across_parent_edits(
    store: Store, tmp_path: Path
) -> None:
    source = tmp_path / "bundle"
    (source / "nested" / "empty").mkdir(parents=True)
    (source / "a.vtu").write_bytes(b"old a")
    (source / "nested/b.vtu").write_bytes(b"old b")
    draft = store.projects.add("source").runs.create(name="parent")
    draft.add_file(source, path="outputs/bundle")
    draft.save(git={})
    parent = draft.project.runs.get(draft.id)
    reference = parent.file("outputs/bundle").ref()
    assert isinstance(reference, DirectoryRef)
    replacement = tmp_path / "new.vtu"
    replacement.write_bytes(b"new a")
    with parent.edit() as edit:
        edit.add_file(replacement, path="outputs/bundle/a.vtu")
    child = store.projects.add("consumer").runs.create(name="child")
    directory = child.input(reference, name="renamed")
    assert (directory / "a.vtu").read_bytes() == b"old a"
    assert (directory / "nested/b.vtu").read_bytes() == b"old b"
    assert (directory / "nested/empty").is_dir()
    child.save(git={})
    run = child.project.runs.get(child.id)
    with pytest.raises(ConflictError, match="directory input"), run.edit() as edit:
        edit.add_file(replacement, path="inputs/renamed/new.vtu")
    assert parent.file("outputs/bundle/a.vtu").materialize().read_bytes() == b"new a"
    assert (
        run.file("inputs/renamed").materialize().joinpath("a.vtu").read_bytes()
        == b"old a"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        reference.path = "outputs/other"


def test_directory_get_export_and_cache_preserve_exact_tree(
    store: Store, tmp_path: Path
) -> None:
    source = tmp_path / "bundle"
    (source / "deep" / "empty").mkdir(parents=True)
    (source / "a.bin").write_bytes(b"a")
    (source / "deep/b.bin").write_bytes(b"b")
    draft = store.projects.add("p").runs.create(name="directory output")
    draft.add_file(source, path="outputs/bundle")
    draft.save(git={})
    run = draft.project.runs.get(draft.id)
    item = run.file("outputs/bundle")
    cached = item.materialize()
    (cached / "a.bin").write_bytes(b"cache corruption")
    (cached / "extra.bin").write_bytes(b"extra")
    restored = item.materialize()
    assert restored == cached
    assert (restored / "a.bin").read_bytes() == b"a"
    assert not (restored / "extra.bin").exists()
    copied = item.copy_to(tmp_path / "get")
    assert (copied / "deep/b.bin").read_bytes() == b"b"
    assert (copied / "deep/empty").is_dir()
    exported = run.export(tmp_path / "export-directory", with_data=True)
    assert (exported / "outputs/bundle/a.bin").read_bytes() == b"a"
    assert (exported / "outputs/bundle/deep/b.bin").read_bytes() == b"b"
    assert (exported / "outputs/bundle/deep/empty").is_dir()
    target = Store.create(
        tmp_path / "directory-archive", cache_root=tmp_path / "archive-cache"
    )
    assert run.copy_to(target).ok
    archived = target.projects.get("p").runs.get(run.id)
    assert archived.fingerprint == run.fingerprint
    assert (archived.file("outputs/bundle").materialize() / "deep/empty").is_dir()


def test_empty_directory_reference_retains_source_ancestry(
    store: Store, tmp_path: Path
) -> None:
    source = tmp_path / "empty"
    source.mkdir()
    draft = store.projects.add("parent").runs.create(name="empty dataset")
    draft.add_file(source, path="outputs/empty")
    draft.save(git={})
    parent = draft.project.runs.get(draft.id)
    reference = parent.file("outputs/empty").ref()
    assert isinstance(reference, DirectoryRef)
    assert not reference.members
    child = store.projects.add("child").runs.create(name="empty consumer")
    bound = child.input(reference, name="data")
    assert bound.is_dir()
    assert not any(bound.iterdir())
    child.save(git={})
    with pytest.raises(ConflictError, match="depends"):
        parent.project.runs.delete(parent.id)
    target = Store.create(
        tmp_path / "empty-archive", cache_root=tmp_path / "empty-cache"
    )
    assert len(child.project.runs.get(child.id).copy_to(target).runs) == 2
    archived = target.projects.get("child").runs.get(child.id)
    result = archived.file("inputs/data").materialize()
    assert result.is_dir()
    assert not any(result.iterdir())


def test_directory_import_resolves_links_and_rejects_cycles_and_overlap(
    store: Store, tmp_path: Path
) -> None:
    actual = tmp_path / "actual.bin"
    actual.write_bytes(b"linked payload")
    source = tmp_path / "linked"
    source.mkdir()
    (source / "value.bin").symlink_to(actual)
    draft = store.projects.add("p").runs.create(name="link import")
    directory = draft.input(source)
    assert (directory / "value.bin").read_bytes() == b"linked payload"
    assert not (directory / "value.bin").is_symlink()
    cyclic = tmp_path / "cyclic"
    cyclic.mkdir()
    (cyclic / "self").symlink_to(cyclic, target_is_directory=True)
    with pytest.raises(IntegrityError, match="cycle"):
        draft.input(cyclic)
    with pytest.raises(ConflictError, match="overlaps"):
        draft.input(draft.directory, name="overlap")


def test_posthoc_directory_reference_is_attachment_with_source_provenance(
    store: Store, tmp_path: Path
) -> None:
    source = tmp_path / "dataset"
    (source / "empty").mkdir(parents=True)
    (source / "value.bin").write_bytes(b"value")
    draft = store.projects.add("parent").runs.create(name="directory source")
    draft.add_file(source, path="outputs/data")
    draft.save(git={})
    parent = draft.project.runs.get(draft.id)
    reference = parent.file("outputs/data").ref()
    child = saved(store, "child")
    path = store.bind_input(child, reference, "inputs/posthoc", consumed=False)
    assert (path / "value.bin").read_bytes() == b"value"
    assert (path / "empty").is_dir()
    assert not child.metadata["input_bindings"]
    assert not child.metadata.get("directory_bindings")
    assert any(
        item["source"]["run"] == parent.id for item in child.metadata["attachments"]
    )
    with pytest.raises(ConflictError, match="depends"):
        parent.project.runs.delete(parent.id)


def test_public_copies_cannot_overwrite_any_authoritative_run(
    store: Store, tmp_path: Path
) -> None:
    source = saved(store, "source", data=b"source")
    other = saved(store, "other", data=b"preserved")
    previous = other.fingerprint
    item = source.file("outputs/result.vtu")
    with pytest.raises(ConflictError, match="authoritative"):
        item.copy_to(other.directory / "run.yaml")
    with pytest.raises(ConflictError, match="authoritative"):
        source.export(other.directory / "nested-export", with_data=True)
    assert other.fingerprint == previous
    foreign = Store.create(
        tmp_path / "foreign-store", cache_root=tmp_path / "foreign-cache"
    )
    with pytest.raises(ConflictError, match="authoritative"):
        item.copy_to(foreign.root / "store.yaml")


def test_save_and_edit_update_only_selected_run_in_primed_index(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    one = saved(store, name="one")
    two = saved(store, name="two")
    store.index.rebuild()
    read_row = store.index._row
    seen: list[str] = []

    def tracked(run: Any) -> Any:
        seen.append(run.id)
        return read_row(run)

    monkeypatch.setattr(store.index, "_row", tracked)
    with one.edit() as edit:
        edit.tags.add("selected")
    assert seen == [one.id]
    seen.clear()
    three = saved(store, name="three")
    assert seen == [three.id]
    assert two.id not in seen


def test_directory_binding_resolves_same_content_after_suffix_updates(
    store: Store, tmp_path: Path
) -> None:
    source = tmp_path / "duplicate-inputs"
    source.mkdir()
    (source / "a.txt").write_bytes(b"same")
    (source / "b.bin").write_bytes(b"same")
    draft = store.projects.add("p").runs.create(name="duplicate directory")
    target = draft.input(source, name="data")
    assert (target / "a.txt").read_bytes() == b"same"
    assert (target / "b.bin").read_bytes() == b"same"
    assert draft.save(git={}).saved
    assert len(store._objects()) == 1


def test_grouped_materializations_keep_each_runs_companion_contents(
    store: Store,
) -> None:
    project = store.projects.add("p")
    records = []
    for value in (b"first mesh", b"second mesh"):
        draft = project.runs.create(name="series")
        draft.output("data.series").write_text(
            '{"files":[{"name":"frame.dat","time":0}]}'
        )
        draft.output("frame.dat").write_bytes(value)
        draft.group("outputs/data.series", files=["outputs/frame.dat"])
        draft.save(git={})
        records.append(project.runs.get(draft.id))
    first = records[0].file("outputs/data.series").materialize()
    second = records[1].file("outputs/data.series").materialize()
    assert first != second
    assert (first.parent / "frame.dat").read_bytes() == b"first mesh"
    assert (second.parent / "frame.dat").read_bytes() == b"second mesh"


def test_invalid_companion_removal_leaves_live_record_and_recovery_clean(
    store: Store, tmp_path: Path
) -> None:
    source = tmp_path / "grouped"
    source.mkdir()
    (source / "a.dat").write_bytes(b"keep this")
    draft = store.projects.add("p").runs.create(name="group")
    draft.add_file(source, path="outputs/data")
    draft.save(git={})
    run = draft.project.runs.get(draft.id)
    before = run.fingerprint
    with pytest.raises(IntegrityError, match="companion"), run.edit() as editor:
        editor.remove_file("outputs/data/a.dat")
    assert run.fingerprint == before
    assert run.file("outputs/data/a.dat").materialize().read_bytes() == b"keep this"
    assert store.recover().ok
    assert not store._transactions()

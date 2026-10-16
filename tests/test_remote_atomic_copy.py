# Copyright (c) 2026 liblaf
# ruff: noqa: SLF001
from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest

from liblaf.cherries import _remote


def test_atomic_copy_removes_temporary_alias_before_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mounted destinations can reject reads while their staging alias exists."""
    source = tmp_path / "source"
    source.write_bytes(b"immutable payload")
    destination = tmp_path / "remote" / "object"
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    original_hash = _remote.sha256_file
    readbacks: list[Path] = []

    def mounted_hash(path: Path) -> str:
        if path == destination:
            aliases = list(path.parent.glob(f".{path.name}.*"))
            if aliases:
                raise OSError(errno.EINVAL, "staging alias still exists", str(path))
            readbacks.append(path)
        return original_hash(path)

    monkeypatch.setattr(_remote, "sha256_file", mounted_hash)
    _remote._atomic_copy(source, destination, expected)
    assert destination.read_bytes() == source.read_bytes()
    assert readbacks == [destination]
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize("matching", [True, False])
def test_atomic_copy_racing_publisher_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, matching: bool
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"expected payload")
    destination = tmp_path / "remote" / "object"
    competing_bytes = source.read_bytes() if matching else b"different payload"
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    original_hash = _remote.sha256_file

    def racing_link(_source: Path, target: Path) -> None:
        target.write_bytes(competing_bytes)
        raise FileExistsError(target)

    def mounted_hash(path: Path) -> str:
        assert not list(path.parent.glob(f".{path.name}.*"))
        return original_hash(path)

    monkeypatch.setattr(os, "link", racing_link)
    monkeypatch.setattr(_remote, "sha256_file", mounted_hash)
    if matching:
        _remote._atomic_copy(source, destination, expected)
    else:
        with pytest.raises(_remote.IntegrityError, match="remote object differs"):
            _remote._atomic_copy(source, destination, expected)
    assert destination.read_bytes() == competing_bytes
    assert list(destination.parent.iterdir()) == [destination]


def test_atomic_copy_checks_published_bytes_after_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"expected payload")
    destination = tmp_path / "remote" / "object"
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    original_link = os.link

    def corrupt_link(staged: Path, target: Path) -> None:
        original_link(staged, target)
        target.write_bytes(b"corrupted payload")

    monkeypatch.setattr(os, "link", corrupt_link)
    with pytest.raises(_remote.IntegrityError, match="read-back hash differs"):
        _remote._atomic_copy(source, destination, expected)
    assert destination.read_bytes() == b"corrupted payload"
    assert list(destination.parent.iterdir()) == [destination]


def test_atomic_copy_preserves_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"new bytes")
    destination = tmp_path / "object"
    destination.write_bytes(b"existing bytes")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(_remote.IntegrityError, match="remote object differs"):
        _remote._atomic_copy(source, destination, expected)
    assert destination.read_bytes() == b"existing bytes"

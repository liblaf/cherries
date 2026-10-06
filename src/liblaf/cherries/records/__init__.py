# Copyright (c) 2026 liblaf
"""Immutable, content-addressed experiment records.

The store is deliberately independent from the experiment runner.  A caller
creates a writable work directory, then seals it once the process succeeds.
"""

from ._store import (
    DeletionBlockedError,
    IntegrityError,
    NotFoundError,
    RecordStoreError,
    Store,
    canonical_json,
    hash_file,
    record_asset_ids,
)

__all__ = [
    "DeletionBlockedError",
    "IntegrityError",
    "NotFoundError",
    "RecordStoreError",
    "Store",
    "canonical_json",
    "hash_file",
    "record_asset_ids",
]

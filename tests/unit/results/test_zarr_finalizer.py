"""The write lock of a field store lives under the attempt state of its run.

``runs/<case>/fields.zarr`` is locked by ``runs/<case>/.hmp/locks/fields.zarr.lock``:
outside the store, so it is never a member of the hierarchy nor of a content
hash, and inside the attempt state, so the seal of a completed run removes it
with the rest of ``<run>/.hmp/``.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.results.zarr_store.zarr_finalizer import lock_path_for_store


def test_two_stores_of_one_directory_never_share_a_lock(tmp_path: Path) -> None:
    first = lock_path_for_store(tmp_path / "a.zarr")
    second = lock_path_for_store(tmp_path / "b.zarr")

    assert first != second
    assert first.parent == second.parent

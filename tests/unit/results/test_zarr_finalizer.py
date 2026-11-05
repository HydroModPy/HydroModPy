"""The write lock of a field store lives under the attempt state of its run.

``runs/<case>/fields.zarr`` is locked by ``runs/<case>/.hmp/locks/fields.zarr.lock``:
outside the store, so it is never a member of the hierarchy nor of a content
hash, and inside the attempt state, so the seal of a completed run removes it
with the rest of ``<run>/.hmp/``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.core.state.layout import INTERNAL_DIRNAME, RUN_INTERNAL_LOCKS_DIRNAME
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME, RUN_SCRATCH_ENTRIES
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.zarr_finalizer import LOCK_SUFFIX, lock_path_for_store


def test_the_lock_sits_under_the_run_attempt_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "nancon_monthly"
    run_dir.mkdir(parents=True)
    store = run_dir / FIELDS_STORE_NAME

    lock = lock_path_for_store(store)

    assert lock == (
        run_dir.resolve()
        / INTERNAL_DIRNAME
        / RUN_INTERNAL_LOCKS_DIRNAME
        / f"{FIELDS_STORE_NAME}{LOCK_SUFFIX}"
    )
    assert INTERNAL_DIRNAME in RUN_SCRATCH_ENTRIES
    assert store.resolve() not in lock.parents


def test_a_write_takes_the_lock_under_the_run_and_leaves_the_store_clean(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "nancon_monthly"
    run_dir.mkdir(parents=True)
    store_path = run_dir / FIELDS_STORE_NAME

    sz = SimulationZarr.create(store_path, n_cells=4, n_layers=1)
    try:
        sz.write_field("head", 0, np.ones(4), n_timesteps=1)
    finally:
        sz.close()

    locks = run_dir / INTERNAL_DIRNAME / RUN_INTERNAL_LOCKS_DIRNAME
    assert (locks / f"{FIELDS_STORE_NAME}{LOCK_SUFFIX}").exists()
    assert not list(store_path.rglob(f"*{LOCK_SUFFIX}")), "no lock file inside the store"


def test_two_stores_of_one_directory_never_share_a_lock(tmp_path: Path) -> None:
    first = lock_path_for_store(tmp_path / "a.zarr")
    second = lock_path_for_store(tmp_path / "b.zarr")

    assert first != second
    assert first.parent == second.parent

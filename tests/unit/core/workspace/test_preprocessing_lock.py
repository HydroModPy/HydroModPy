"""D13: the inter-process lock guarding .hmp/scratch/_preprocessing/."""

from __future__ import annotations

from pathlib import Path

import pytest
from filelock import Timeout

from hydromodpy.core.workspace.path_registry import (
    PREPROCESSING_LOCK_FILENAME,
    preprocessing_lock,
)


def test_preprocessing_lock_lives_under_hmp_locks(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    lock = preprocessing_lock(project_root)

    assert Path(lock.lock_file).parent == project_root / ".hmp" / "locks"
    assert Path(lock.lock_file).name == PREPROCESSING_LOCK_FILENAME
    assert (project_root / ".hmp" / "locks").is_dir()


def test_preprocessing_lock_blocks_a_concurrent_holder(tmp_path: Path) -> None:
    """One process holding the lock makes a second one time out.

    This is what makes two ``hmp run`` invocations on the same project
    serialize through the geographic/mesh preprocessing phase instead of
    interleaving their writes and reads of the shared scratch tree.
    """
    project_root = tmp_path / "project"
    holder = preprocessing_lock(project_root)
    holder.acquire()
    try:
        contender = preprocessing_lock(project_root)
        with pytest.raises(Timeout):
            contender.acquire(timeout=0.2)
    finally:
        holder.release()

    # Once released, the next caller acquires it immediately.
    with preprocessing_lock(project_root):
        pass

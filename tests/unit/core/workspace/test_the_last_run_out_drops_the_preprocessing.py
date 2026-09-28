"""A run's cleanup drops the preprocessing tree only when no other run still reads it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.core.workspace import path_registry
from hydromodpy.core.workspace.path_registry import (
    PREPROCESSING_USERS_FILENAME,
    hold_preprocessing_use,
    preprocessing_unused,
    project_root_of_internal_path,
    release_preprocessing_use,
)

fcntl = pytest.importorskip("fcntl")

pytestmark = pytest.mark.unit


def _other_reader(project_root: Path) -> int:
    """Open the users file on its own descriptor and lock it shared, as another run does."""
    users = project_root / ".hmp" / "locks" / PREPROCESSING_USERS_FILENAME
    users.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(users, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_SH)
    return fd


def test_nobody_else_reading_lets_the_cleanup_drop(tmp_path: Path) -> None:
    with preprocessing_unused(tmp_path) as unused:
        assert unused is True


def test_another_reader_keeps_the_tree(tmp_path: Path) -> None:
    fd = _other_reader(tmp_path)
    try:
        with preprocessing_unused(tmp_path) as unused:
            assert unused is False
    finally:
        os.close(fd)
    with preprocessing_unused(tmp_path) as unused:
        assert unused is True


def test_this_process_must_release_its_own_use_first(tmp_path: Path) -> None:
    hold_preprocessing_use(tmp_path)
    hold_preprocessing_use(tmp_path)
    try:
        assert len([k for k in path_registry._HELD_USES if k == str(tmp_path.resolve())]) == 1
        with preprocessing_unused(tmp_path) as unused:
            assert unused is False
    finally:
        release_preprocessing_use(tmp_path)
    with preprocessing_unused(tmp_path) as unused:
        assert unused is True


def test_the_cleanup_keeps_a_tree_another_run_reads(tmp_path: Path) -> None:
    from hydromodpy.spatial.geographic.store_ingestion import cleanup_stable_folder

    stable = tmp_path / ".hmp" / "scratch" / "_preprocessing"
    (stable / "geographic").mkdir(parents=True)
    (stable / "geographic" / "outlet.shp").write_bytes(b"x")

    class _Geographic:
        stable_folder = stable

    fd = _other_reader(tmp_path)
    try:
        assert cleanup_stable_folder(_Geographic()) == 0
        assert (stable / "geographic" / "outlet.shp").is_file()
    finally:
        os.close(fd)

    assert cleanup_stable_folder(_Geographic()) > 0
    assert not stable.exists()


def test_the_project_root_is_found_above_hmp(tmp_path: Path) -> None:
    path = tmp_path / "proj" / ".hmp" / "scratch" / "_preprocessing"
    path.mkdir(parents=True)

    assert project_root_of_internal_path(path) == (tmp_path / "proj").resolve()
    assert project_root_of_internal_path(tmp_path / "elsewhere") is None

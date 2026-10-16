"""A bare name is the live directory ``runs/<name>``, never a trashed one.

The trash is a directory of its own: a trashed run leaves ``runs/`` and its
name answers nothing there any more. Reading it back goes through the trash
listing, and ``restore`` is the only way out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.results.catalog.discovery import (
    SimulationNotFoundError,
    resolve_rel_dir,
    resolve_trashed,
)
from hydromodpy.results.trash import restore, trash_run

AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def _run(project: Path, name: str) -> None:
    (project / "runs" / name).mkdir(parents=True)


def test_a_trashed_name_answers_nothing_in_the_tree(tmp_path: Path) -> None:
    _run(tmp_path, "x")
    trash_run(tmp_path, "runs/x", now=AT)
    with pytest.raises(SimulationNotFoundError):
        resolve_rel_dir(tmp_path, "x")


def test_a_bare_name_never_slides_to_another_version(tmp_path: Path) -> None:
    _run(tmp_path, "x")
    _run(tmp_path, "x.v2")
    trash_run(tmp_path, "runs/x", now=AT)
    with pytest.raises(SimulationNotFoundError):
        resolve_rel_dir(tmp_path, "x")
    assert resolve_rel_dir(tmp_path, "x.v2") == "runs/x.v2"


def test_the_trash_listing_is_what_restore_reads(tmp_path: Path) -> None:
    _run(tmp_path, "x")
    trash_run(tmp_path, "runs/x", now=AT)
    entry = resolve_trashed(tmp_path, "x")
    restore(tmp_path, entry.name)
    assert resolve_rel_dir(tmp_path, "x") == "runs/x"

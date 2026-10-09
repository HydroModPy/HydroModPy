"""A name a live and a trashed run both hold is never purged by a guess.

``if_exists = "replace"`` trashes the old ``x`` and registers ``x.v2``. The
trash lists the old run as ``x``, while a bare ``x`` resolves to the live
``x.v2``. ``hmp catalog delete x --now`` purged the live run.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.cli._workers.catalog import delete_simulation, restore_simulation
from hydromodpy.results.catalog.discovery import AmbiguousReferenceError
from tests._helpers.fixtures_catalog import simulation_catalog


def _run(cat, name: str, *, if_exists: str = "version") -> str:
    sid = str(uuid.uuid4())
    cat.register_simulation(sid, project="p", solver="modflow6", name=name, if_exists=if_exists)
    cat.finalize(sid, "completed")
    return sid


def _replaced(root: Path) -> tuple[str, str]:
    with simulation_catalog(root) as cat:
        old = _run(cat, "x")
        new = _run(cat, "x", if_exists="replace")
    return old, new


def test_a_purge_by_a_shared_name_is_refused_with_both_ids(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    old, new = _replaced(root)

    with pytest.raises(AmbiguousReferenceError) as caught:
        delete_simulation("x", workspace=root)
    assert {sid for sid, _ in caught.value.candidates} == {old, new}

    with simulation_catalog(root) as cat:
        assert cat.resolve(new) == new
        assert cat.resolve(old) == old


def test_a_purge_by_id_still_works(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    old, new = _replaced(root)
    assert delete_simulation(old, workspace=root)["sim_id"] == old
    with simulation_catalog(root) as cat:
        assert cat.resolve("x") == new


def test_restore_by_name_reads_the_trash(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    old, _new = _replaced(root)
    assert restore_simulation("x", workspace=root)["sim_id"] == old


def test_restore_finds_a_run_trashed_by_hand(tmp_path: Path) -> None:
    """``Catalog.trash`` frees the name; the trash still lists it as ``original_name``."""
    root = tmp_path / "ws"
    with simulation_catalog(root) as cat:
        sid = _run(cat, "y")
        cat.trash(sid)
    assert restore_simulation("y", workspace=root)["sim_id"] == sid

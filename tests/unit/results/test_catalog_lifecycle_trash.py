"""Trash / restore / tag / note lifecycle for the simulation catalog."""

from __future__ import annotations

import uuid

import pytest

from hydromodpy.core.state.paths import share_dir_for
from hydromodpy.results.catalog import (
    AmbiguousReferenceError,
    DuplicateSimulationNameError,
)
from hydromodpy.results.catalog.lifecycle import PinnedRunError
from hydromodpy.results.storage.contract import TABLES_DIRNAME
from hydromodpy.results.trash_marker import read_trash_marker
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _register(catalog, name):
    sid = str(uuid.uuid4())
    catalog.register_simulation(sid, project="p", solver="modflow6", name=name)
    catalog._backend.execute(
        "UPDATE simulations SET status_id = (SELECT id FROM statuses WHERE code = 'completed'), "
        "ended_at = current_timestamp WHERE sim_id = ?",
        [sid],
    )
    return sid


def test_add_tag_is_idempotent_and_write_tags_skips_blanks(catalog):
    sid = _register(catalog, "r")
    assert catalog.add_tag(sid, "paper") is True
    assert catalog.add_tag(sid, "paper") is False
    catalog.write_tags(sid, ["2019", "", "  "])
    tags = {
        r[0] for r in catalog._backend.fetch_all("SELECT tag FROM tags WHERE sim_id = ?", [sid])
    }
    assert tags == {"paper", "2019"}


def test_add_note_appends_to_sim_notes(catalog):
    sid = _register(catalog, "r")
    catalog.add_note(sid, "first")
    catalog.add_note(sid, "second")
    notes = [
        r[0]
        for r in catalog._backend.fetch_all("SELECT note FROM sim_notes WHERE sim_id = ?", [sid])
    ]
    assert sorted(notes) == ["first", "second"]


def test_trash_frees_name_keeps_storage_and_restore_versions(catalog):
    sid = _register(catalog, "baseline")
    catalog.trash(sid)
    row = catalog._backend.fetch_one(
        "SELECT name, original_name, st.code FROM simulations s "
        "JOIN statuses st ON s.status_id = st.id WHERE sim_id = ?",
        [sid],
    )
    assert row == (None, "baseline", "trashed")
    assert [e["original_name"] for e in catalog.list_trash()] == ["baseline"]

    # Trashing frees the name in the index, not the directory: the bytes stay
    # so the run stays restorable. A newcomer asking for the name therefore
    # gets the next version, and the restore keeps the name nobody took.
    fresh = str(uuid.uuid4())
    reused = catalog.register_simulation(fresh, project="p", solver="modflow6", name="baseline")
    assert reused.name == "baseline.v2"
    assert catalog.restore(sid) == "baseline"
    assert catalog.list_trash() == []


def test_restore_of_a_version_keeps_its_free_name(catalog):
    _register(catalog, "baseline")
    second = catalog.register_simulation(
        str(uuid.uuid4()), project="p", solver="modflow6", name="baseline"
    )
    assert second.name == "baseline.v2"
    catalog.trash(second.sim_id)

    assert catalog.restore(second.sim_id) == "baseline.v2"
    row = catalog._backend.fetch_one(
        "SELECT name_stem, version_int, storage_basename FROM simulations WHERE sim_id = ?",
        [second.sim_id],
    )
    assert row[0] == "baseline"
    assert row[1] == 2


def test_restore_versions_when_another_run_took_the_name(catalog):
    sid = _register(catalog, "baseline")
    catalog.trash(sid)
    fresh = catalog.register_simulation(
        str(uuid.uuid4()), project="p", solver="modflow6", name="baseline"
    )
    # A run that now answers to the old name, as an import or a rename leaves it.
    catalog._backend.execute(
        "UPDATE simulations SET name = 'baseline' WHERE sim_id = ?", [fresh.sim_id]
    )
    assert catalog.restore(sid) == "baseline.v3"

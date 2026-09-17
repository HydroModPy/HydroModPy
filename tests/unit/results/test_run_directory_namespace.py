"""A run directory name is unique in the catalog, not in the project.

A catalog owns exactly one ``runs/`` tree and registration writes
``runs/<name>/fields.zarr``, with no project segment. ``project`` is a label
on a row. Every test here pins that the scope of a run name is the scope of
the directory it names, along the three axes where the two used to disagree:
two projects of one catalog, a name a trashed run still occupies on disk, and
a rename.
"""

from __future__ import annotations

import uuid

import duckdb
import pytest

from hydromodpy.results.catalog import registration as registration_mod
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _register(catalog, sim_id=None, **kwargs):
    sid = sim_id or str(uuid.uuid4())
    defaults = dict(project="alpha", solver="modflow6", n_cells=10, n_layers=2)
    defaults.update(kwargs)
    reg = catalog.register_simulation(sid, **defaults)
    if reg.zarr is not None:
        reg.zarr.close()
    return sid, reg.name


def _colliding_sim_ids() -> tuple[str, str]:
    """Return two ``sim_id`` that the memorable slug maps to the same name.

    The slug draws from 16 adjectives x 16 nouns, so a pair shows up after a
    couple of dozen draws; the loop is bounded so a wider vocabulary makes the
    test fail loudly instead of hanging.
    """
    seen: dict[str, str] = {}
    for _ in range(100_000):
        sid = str(uuid.uuid4())
        slug = registration_mod._memorable_name(sid)
        if slug in seen:
            return seen[slug], sid
        seen[slug] = sid
    raise AssertionError("no memorable-name collision in 100 000 draws")


def test_two_projects_of_one_catalog_do_not_fight_over_a_directory(catalog):
    """Two projects drawing one name both register, in two directories.

    The memorable slug is a function of ``sim_id`` alone, so two runs collide
    on it at 0.39 % per pair. Auto-versioning used to be keyed on the project,
    so the second run kept the bare name and died on ``FileExistsError`` when
    its Zarr store landed on the first run's directory.
    """
    first_id, second_id = _colliding_sim_ids()
    _, first_name = _register(catalog, sim_id=first_id, project="alpha")
    _, second_name = _register(catalog, sim_id=second_id, project="beta")

    assert first_name != second_name
    assert second_name == f"{first_name}.v2"
    assert catalog.run_dir_for(first_id) != catalog.run_dir_for(second_id)
    assert catalog.fields_path_for(first_id).is_dir()
    assert catalog.fields_path_for(second_id).is_dir()


def test_an_explicit_name_is_versioned_across_projects_too(catalog):
    """The same holds for a name the caller typed, not only for a drawn one."""
    _, first_name = _register(catalog, project="alpha", name="cheze_baseline")
    _, second_name = _register(catalog, project="beta", name="cheze_baseline")

    assert (first_name, second_name) == ("cheze_baseline", "cheze_baseline.v2")


def test_replace_never_trashes_a_neighbour_project(catalog):
    """``if_exists`` still answers a question about the caller's project.

    The directory namespace is the catalog, but ``replace`` is an instruction
    about the run the caller owns: a neighbour project that happens to have
    picked the same word keeps its run alive.
    """
    neighbour, _ = _register(catalog, project="beta", name="shared")
    _register(catalog, project="alpha", name="shared", if_exists="replace")

    status = catalog.connection.execute(
        "SELECT st.code FROM simulations s JOIN statuses st ON s.status_id = st.id "
        "WHERE CAST(s.sim_id AS VARCHAR) = ?",
        [neighbour],
    ).fetchone()
    assert status[0] != "trashed"


def test_fail_refuses_a_name_a_neighbour_project_holds(catalog):
    """``if_exists='fail'`` exists to forbid a substitute name.

    It refuses on a live run of the caller's project, and on a directory any
    project holds: minting ``.v2`` under ``fail`` would be the one thing the
    mode was chosen to prevent. The error names the project that holds it.
    """
    neighbour, _ = _register(catalog, project="beta", name="shared")

    with pytest.raises(registration_mod.DuplicateSimulationNameError) as excinfo:
        _register(catalog, project="alpha", name="shared", if_exists="fail")
    assert excinfo.value.project == "beta"
    assert excinfo.value.existing_sim_id == neighbour

    _, own = _register(catalog, project="alpha", name="mine", if_exists="fail")
    assert own == "mine"
    with pytest.raises(registration_mod.DuplicateSimulationNameError) as excinfo:
        _register(catalog, project="alpha", name="mine", if_exists="fail")
    assert excinfo.value.project == "alpha"


def test_fail_refuses_a_name_a_trashed_run_still_occupies(catalog):
    """A trashed run keeps its directory, so its name is not free under ``fail``."""
    sid, _ = _register(catalog, project="alpha", name="gone")
    catalog.trash(sid)

    with pytest.raises(registration_mod.DuplicateSimulationNameError):
        _register(catalog, project="alpha", name="gone", if_exists="fail")


def test_a_name_a_trashed_run_still_occupies_is_versioned(catalog):
    """Trashing frees the name in the index and leaves the directory in place.

    The bytes stay so the run stays restorable, so the name is not free for a
    newcomer: it maps to a directory that still exists.
    """
    first_id, _ = _register(catalog, project="alpha", name="recycled")
    catalog.trash(first_id)

    second_id, second_name = _register(catalog, project="alpha", name="recycled")
    assert second_name == "recycled.v2"
    assert catalog.run_dir_for(first_id).is_dir()
    assert catalog.run_dir_for(second_id) != catalog.run_dir_for(first_id)


def test_restoring_a_trashed_run_takes_its_own_directory_back(catalog):
    """A run's own directory is not an obstacle to restoring it."""
    sid, _ = _register(catalog, project="alpha", name="recycled")
    catalog.trash(sid)

    assert catalog.restore(sid) == "recycled"
    assert catalog.run_dir_for(sid).name == "recycled"


def test_restoring_behind_a_successor_still_mints_a_version(catalog):
    """When the name was taken meanwhile, the restored run gets the next one."""
    sid, _ = _register(catalog, project="alpha", name="recycled")
    catalog.trash(sid)
    _register(catalog, project="alpha", name="recycled")

    assert catalog.restore(sid) == "recycled.v3"


def test_renaming_onto_a_directory_of_another_project_is_refused(catalog):
    """A rename is a name the caller chose: a taken directory is a refusal."""
    _register(catalog, project="beta", name="taken")
    sid, _ = _register(catalog, project="alpha", name="mine")

    with pytest.raises(registration_mod.DuplicateSimulationNameError):
        catalog.rename_simulation(sid, "taken")


def test_renaming_onto_the_directory_of_a_trashed_run_is_refused(catalog):
    """The directory of a trashed run is still a directory."""
    trashed_id, _ = _register(catalog, project="alpha", name="gone")
    catalog.trash(trashed_id)
    sid, _ = _register(catalog, project="alpha", name="mine")

    with pytest.raises(registration_mod.DuplicateSimulationNameError):
        catalog.rename_simulation(sid, "gone")


def test_the_index_refuses_two_rows_on_one_directory(catalog):
    """The schema carries the invariant, so no writer can go around it.

    ``UNIQUE (project, name)`` lets two projects share a name; the unique index
    on ``storage_basename`` is what matches the tree, and it covers the writers
    that do not go through registration (rebuild, package import).
    """
    first_id, _ = _register(catalog, project="alpha", name="one")
    second_id, _ = _register(catalog, project="beta", name="two")

    with pytest.raises(duckdb.ConstraintException):
        catalog.connection.execute(
            "UPDATE simulations SET storage_basename = 'one' WHERE CAST(sim_id AS VARCHAR) = ?",
            [second_id],
        )

    assert first_id != second_id

"""A refinement zone reads the field of an earlier sealed run of the project.

The run is named like ``[flow] restart_from`` names one: by its name or its
sim_id. Its water-table depth and its seepage are reduced to their extremes
over every time step, per cell of its mesh, so a cell that came close to the
ground or seeped once counts. A run that does not exist, is not sealed, or
lacks the field is refused.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.run.field_envelope import read_run_field, read_run_fields
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.spatial.mesh.planning.refinement_zones import CriterionInputs, load_refinement_zones
from hydromodpy.spatial.mesh.refinement_config import RefinementZoneConfig
from tests._helpers.mesh_cases import grid_spec
from tests._helpers.run_stores import open_run_store

N_STEPS = 3
CELL = 100.0
TOP = np.array([100.0, 100.0, 100.0, 100.0])

# Water table per step and cell: cell 0 comes within 0.25 m of the ground at
# step 1 only, cell 1 stays 5 m deep, cell 2 is dry at step 0, cell 3 seeps.
# Every value is a sum of a few powers of two, so the store keeps it exactly
# (it rounds its fields to 16 significant bits, TOLERANCES.md row 178).
WATER_TABLE = np.array(
    [
        [97.0, 95.0, np.nan, 100.0],
        [99.75, 95.0, 96.0, 100.0],
        [98.0, 95.0, 97.0, 100.0],
    ]
)
# Drain outflow [m3/s], negative leaves the aquifer. Over a 1e4 m2 cell, q m3/s
# is q * 8640 mm/d: 2**-13 m3/s is 1.0546875 mm/d, 2**-16 m3/s is 0.1318359375 mm/d.
DRAIN = np.array(
    [
        [0.0, 0.0, 0.0, -(2.0**-13)],
        [-(2.0**-16), 0.0, 0.0, -(2.0**-14)],
        [0.0, 0.0, 0.0, 0.0],
    ]
)


def _squares() -> tuple[np.ndarray, np.ndarray]:
    """Four 100 m squares, two by two, the south-west one first."""
    xs = np.array([0.0, CELL, 2 * CELL])
    vertices = np.array([[x, y, 0.0] for y in xs for x in xs])
    connectivity = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]])
    return vertices, connectivity.astype("int32")


def _run(project: Path, name: str, *, budget: bool = True, seal: bool = True) -> str:
    store = open_run_store(project, name, n_cells=4, n_layers=1, n_timesteps=N_STEPS)
    sim_id = store.sim_id
    vertices, connectivity = _squares()
    handle = store.open_zarr(sim_id)
    try:
        handle.write_mesh(vertices, connectivity, np.array([100.0, 50.0]), topography=TOP)
        handle.write_field_stack("head", WATER_TABLE[:, None, :])
        if budget:
            handle.write_field_stack("drain", DRAIN[:, None, :], subgroup="budget")
    finally:
        handle.close()
    if seal:
        seal_completed(store)
    else:
        store.close()
    return sim_id


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


def test_the_depth_is_reduced_to_its_extremes_over_every_step(project: Path) -> None:
    sim_id = _run(project, "coarse")

    envelope = read_run_field(project, "coarse", "watertable_depth")

    assert envelope.sim_id == sim_id and envelope.run == "coarse" and envelope.unit == "m"
    np.testing.assert_array_equal(envelope.minimum, [0.25, 5.0, 3.0, 0.0])
    np.testing.assert_array_equal(envelope.maximum, [3.0, 5.0, 4.0, 0.0])
    assert envelope.passing(below=0.5, above=None).tolist() == [True, False, False, True]


def test_the_seepage_is_the_drain_outflow_per_area_in_mm_per_day(project: Path) -> None:
    _run(project, "coarse")

    envelope = read_run_field(project, "coarse", "seepage")

    assert envelope.unit == "mm/d"
    np.testing.assert_allclose(envelope.maximum, [0.1318359375, 0.0, 0.0, 1.0546875], rtol=1e-12)
    np.testing.assert_array_equal(envelope.minimum, [0.0, 0.0, 0.0, 0.0])


def test_a_run_is_named_by_its_name_or_its_sim_id(project: Path) -> None:
    sim_id = _run(project, "coarse")

    by_id = read_run_field(project, sim_id, "watertable_depth")

    assert by_id.sim_id == sim_id and by_id.run == "coarse"


def test_a_missing_or_unsealed_run_or_a_missing_field_is_refused(project: Path) -> None:
    _run(project, "open", seal=False)
    _run(project, "dry", budget=False)

    with pytest.raises(ConfigError, match="names no run"):
        read_run_field(project, "nowhere", "watertable_depth")
    with pytest.raises(ConfigError, match="not sealed"):
        read_run_field(project, "open", "watertable_depth")
    with pytest.raises(ConfigError, match="no drain budget"):
        read_run_field(project, "dry", "seepage")


def test_the_zone_of_a_stored_run_holds_the_pixels_of_its_shallow_cells(project: Path) -> None:
    sim_id = _run(project, "coarse")
    zones = [
        RefinementZoneConfig(where="watertable_depth", below=0.5, run="coarse", cell_size=25.0),
        RefinementZoneConfig(where="seepage", above=0.5, run="coarse", cell_size=25.0),
    ]
    grid = grid_spec(8, 8, 25.0)

    fields = read_run_fields(project, zones)
    shallow, seeping = load_refinement_zones(
        zones,
        config_dir=None,
        data_dir=None,
        crs_wkt=grid.crs_wkt,
        criteria=CriterionInputs(
            grid=grid, elevation=np.zeros((8, 8)), stream_lines=None, run_fields=fields
        ),
    )

    assert sorted(fields) == [("coarse", "seepage"), ("coarse", "watertable_depth")]
    assert shallow.source_run == seeping.source_run == sim_id
    south_west, north_east = np.zeros((8, 8), dtype=bool), np.zeros((8, 8), dtype=bool)
    south_west[4:, :4] = True
    north_east[:4, 4:] = True
    np.testing.assert_array_equal(shallow.region.mask, south_west | north_east)
    np.testing.assert_array_equal(seeping.region.mask, north_east)

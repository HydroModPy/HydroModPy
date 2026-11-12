"""Maps of a network output on the solver mesh: observed cells, heads, catchment.

Lengths are in metres. The V-valley bench (cells of 100 m) gives the mesh and the
mapped talweg, which starts on row 12 for the complete map and row 4 for the
permanent one.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.observations.network_geometry import (
    _length_in_m,
    aquifer_extent,
    dense_face_connectivity,
    network_maps_from_run,
)
from hydromodpy.catchment.stream_network.geometry import scored_cells
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_ROWS,
    build_bench,
    cell_id,
)
from tests.unit.calibration._factories_scoring import make_trial_ctx

CRS = "EPSG:2154"
PERMANENT_FIRST_ROW = 4
DAM_FOOT = cell_id(40, AXIS_COL - 6)


def axis_line(first_row: int) -> LineString:
    return LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(first_row, N_ROWS)
        ]
    )


def axis_network(first_row: int):
    lines = gpd.GeoDataFrame(geometry=[axis_line(first_row)], crs=CRS)
    return SimpleNamespace(
        vector_path=f"/fake/axis_{first_row}.gpkg", crs=CRS, read_vector=lambda: lines
    )


def axis_mask(first_row: int) -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[cell_id(row, AXIS_COL) for row in range(first_row, N_ROWS)]] = True
    return mask


def heads_ctx(dam_foot_cells=None):
    networks = {
        "reference": axis_network(FIRST_OBSERVED_ROW),
        "reference_permanent": axis_network(PERMANENT_FIRST_ROW),
        "generated": None,
    }
    return make_trial_ctx(build_bench(), networks=networks, dam_foot_cells=dam_foot_cells)


def heads_output(map=None):
    return validate_calib_output(
        {
            "support": "network",
            "map": {
                "complete": "data.hydrography",
                "drawn_by": "heads",
                "heads": {"min_drained_area": 0.0},
                **(map or {}),
            },
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )


@pytest.fixture(scope="module")
def file_output(tmp_path_factory):
    path = tmp_path_factory.mktemp("network") / "streams.gpkg"
    gpd.GeoDataFrame(geometry=[axis_line(FIRST_OBSERVED_ROW)], crs=CRS).to_file(path, driver="GPKG")
    return validate_calib_output(
        {
            "support": "network",
            "map": {"complete": str(path)},
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )


PERMANENT_MAP = {"permanent": "data.hydrography", "calibrate_on": "permanent"}


def test_minimal_map_gets_the_dam_foot_and_stays_inside_the_maximal_trace():
    ctx = heads_ctx(dam_foot_cells={"reservoir": DAM_FOOT})

    maps = network_maps_from_run(ctx, heads_output(map=PERMANENT_MAP))

    assert maps.minimal is not None and maps.minimal.heads is not None
    assert maps.minimal.heads.forced_cell.tolist() == [DAM_FOOT]
    assert maps.minimal.observed[DAM_FOOT]
    assert not (maps.minimal.observed & ~maps.maximal.observed).any()


def test_maximal_heads_map_contains_the_minimal_trace():
    # The complete network starts on row 12 and the permanent one on row 4, which the
    # complete network does not draw. The maximal map is then the axis from row 4.
    # The permanent trace missed by the complete heads is rows 4 to 11.
    maps = network_maps_from_run(heads_ctx(), heads_output(map=PERMANENT_MAP))

    assert maps.minimal is not None
    np.testing.assert_array_equal(maps.minimal.observed, axis_mask(PERMANENT_FIRST_ROW))
    np.testing.assert_array_equal(maps.maximal.observed, axis_mask(PERMANENT_FIRST_ROW))
    assert maps.frac_minimal_outside_maximal == pytest.approx(
        (FIRST_OBSERVED_ROW - PERMANENT_FIRST_ROW) / (N_ROWS - PERMANENT_FIRST_ROW)
    )


def run_with(*, botm=None, top=(5.0, 6.0, 7.0), mask=None) -> SimpleNamespace:
    mesh = SimpleNamespace(botm=botm, top=np.array(top))
    model = SimpleNamespace(solver_mesh=mesh, inactive_mask=mask)
    return SimpleNamespace(solver_run=SimpleNamespace(solver_model=model))


AQUIFER_EXTENTS = [
    pytest.param(run_with(), None, None, id="none carried"),
    pytest.param(
        run_with(botm=np.array([1.0, 2.0, 3.0])), [4.0, 4.0, 4.0], None, id="one layer base"
    ),
    pytest.param(
        run_with(botm=np.zeros((2, 3)), mask=[True, False, True]),
        [5.0, 6.0, 7.0],
        [True, False, True],
        id="lowest layer base",
    ),
    pytest.param(
        run_with(botm=np.zeros(2), mask=[True, False]), None, None, id="another cell count"
    ),
]


@pytest.mark.parametrize(("run_ctx", "thickness", "inactive"), AQUIFER_EXTENTS)
def test_aquifer_thickness_and_closed_columns(run_ctx, thickness, inactive):
    imposed, closed = aquifer_extent(run_ctx, 3)

    assert (imposed if imposed is None else imposed.tolist()) == thickness
    assert (closed if closed is None else closed.tolist()) == inactive


@pytest.mark.parametrize("ids", [None, []], ids=["no attribute value", "no lake"])
def test_model_without_open_water_excludes_nothing(file_output, ids):
    ctx = make_trial_ctx(build_bench(), geographic={})
    ctx.solver_run.solver_model.open_water_cell_ids = ids

    geometry = network_maps_from_run(ctx, file_output).maximal

    assert geometry.excluded is None
    np.testing.assert_array_equal(scored_cells(geometry), geometry.catchment)


def test_length_in_metres_from_a_quantity_or_a_number():
    assert _length_in_m(SimpleNamespace(to=lambda unit: SimpleNamespace(magnitude=2.5))) == 2.5
    assert _length_in_m(3) == 3.0


MODEL_REFUSALS = [
    pytest.param(None, "no model recorded for run 'r'", id="no model"),
    pytest.param(SimpleNamespace(), "exposes no 'solver_mesh'", id="no mesh"),
    pytest.param(
        SimpleNamespace(solver_mesh=SimpleNamespace()), "exposes no 'cell_centers'", id="no centers"
    ),
]


@pytest.mark.parametrize(("model", "message"), MODEL_REFUSALS)
def test_model_refusals(model, message):
    run_ctx = SimpleNamespace(
        solver_run=SimpleNamespace(solver_model=model), run=SimpleNamespace(id="r")
    )

    with pytest.raises(ValueError, match=message):
        network_maps_from_run(run_ctx, None)


def test_mesh_with_no_cell_is_refused():
    with pytest.raises(ValueError, match="the planar mesh holds no cell"):
        dense_face_connectivity(SimpleNamespace(flat_connectivity=[], vertices=[]))

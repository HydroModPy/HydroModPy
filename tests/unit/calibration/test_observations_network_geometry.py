"""Tests of `observations.network_geometry`."""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.observations.network_geometry import (
    dam_foot_cells_of_model,
    network_maps_from_run,
)
from hydromodpy.calibration.observations.observed_network import delineated_outlet_xy
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    FIRST_OBSERVED_ROW,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    cell_id,
)
from tests.unit.calibration._factories_scoring import make_trial_ctx

# From test_the_criterion_closes_on_the_snapped_outlet.py
# A trial places its outlet from the pour point the geographic step snapped.
#
# The delineation closed the catchment on the snapped outlet, not on the declared
# one. The criterion reads that point off the geographic runtime object and
# moves it within two cells onto the most accumulated cell of its own graph.


CRS = "EPSG:2154"


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    line = LineString([_centre(row, AXIS_COL) for row in range(FIRST_OBSERVED_ROW, N_ROWS)])
    path = tmp_path_factory.mktemp("network") / "streams.gpkg"
    gpd.GeoDataFrame(geometry=[line], crs=CRS).to_file(path, driver="GPKG")
    return validate_calib_output(
        {
            "support": "network",
            "map": {"complete": str(path)},
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )


class TestTheSnappedPointIsRead:
    def test_it_is_the_snapped_point_not_the_declared_one(self) -> None:
        ctx = _run_ctx(x_outlet=1.0, y_outlet=2.0, x_outlet_snapped=3.0, y_outlet_snapped=4.0)

        assert delineated_outlet_xy(ctx) == (3.0, 4.0)

    @pytest.mark.parametrize(
        "geographic",
        [{}, {"x_outlet_snapped": None, "y_outlet_snapped": None}, {"x_outlet_snapped": 3.0}],
    )
    def test_a_catchment_drawn_as_a_polygon_has_none(self, geographic) -> None:
        assert delineated_outlet_xy(_run_ctx(**geographic)) is None


class TestTheTrialClosesOnIt:
    def test_a_point_one_cell_off_the_outlet_lands_on_it(self, output) -> None:
        x, y = _centre(N_ROWS - 2, AXIS_COL + 1)
        maps = network_maps_from_run(_run_ctx(x_outlet_snapped=x, y_outlet_snapped=y), output)
        geometry = maps.maximal

        assert geometry.outlet == cell_id(N_ROWS - 1, AXIS_COL)
        assert geometry.catchment.all()

    def test_a_point_on_a_hillslope_closes_a_smaller_catchment(self, output) -> None:
        x, y = _centre(N_ROWS - 1, 2)
        maps = network_maps_from_run(_run_ctx(x_outlet_snapped=x, y_outlet_snapped=y), output)
        geometry = maps.maximal

        assert geometry.outlet != cell_id(N_ROWS - 1, AXIS_COL)
        assert 0 < int(geometry.catchment.sum()) < N_CELLS
        # No watershed polygon on this run, so there is no gap to publish.
        assert np.isnan(geometry.diagnostics["catchment_mismatch"])


# From test_the_heads_maps_receive_the_dam_foot_of_the_model.py
# The heads maps of a calibration take the dam foot of the built model as a head.
#
# The build leaves ``{lake id: cell}`` on the model: the cell below each dam, where
# the stream under the reservoir starts. Both maps of a heads output (the maximal
# and the minimal) are traced from it as well as from the free ends of their
# files. A model without lakes, or a backend that sets none, draws as before.


PERMANENT_FIRST_ROW = 4
DAM_FOOT = cell_id(40, AXIS_COL - 6)


def _run_ctx(**geographic):
    return make_trial_ctx(build_bench(), geographic=geographic)


def _run_ctx__heads_maps(bench, dam_foot_cells=None):
    networks = {
        "reference": _axis_network(FIRST_OBSERVED_ROW),
        "reference_permanent": _axis_network(PERMANENT_FIRST_ROW),
        "generated": None,
    }
    return make_trial_ctx(bench, networks=networks, dam_foot_cells=dam_foot_cells)


def _axis_network(first_row: int):
    talweg = LineString(
        [
            ((AXIS_COL + 0.5) * CELL_SIZE, (row + 0.5) * CELL_SIZE)
            for row in range(first_row, N_ROWS)
        ]
    )
    lines = gpd.GeoDataFrame(geometry=[talweg], crs=CRS)
    return SimpleNamespace(
        vector_path=f"/fake/axis_{first_row}.gpkg", crs=CRS, read_vector=lambda: lines
    )


def _output(map=None, **extra):
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
            **extra,
        }
    )


def _descent_of(cells, downstream):
    walk = []
    cell = int(cells)
    while cell >= 0:
        walk.append(cell)
        cell = int(downstream[cell])
    return walk


def test_the_maximal_map_is_traced_from_the_dam_foot_of_the_model() -> None:
    bench = build_bench()
    plain = network_maps_from_run(_run_ctx__heads_maps(bench), _output())
    forced = network_maps_from_run(
        _run_ctx__heads_maps(bench, dam_foot_cells={"reservoir": DAM_FOOT}), _output()
    )

    assert not plain.maximal.observed[DAM_FOOT]
    assert forced.maximal.observed[DAM_FOOT]
    for cell in _descent_of(DAM_FOOT, forced.maximal.metric.graph.downstream):
        assert forced.maximal.observed[cell]
    assert forced.maximal.heads is not None
    assert forced.maximal.heads.forced_cell.tolist() == [DAM_FOOT]
    assert forced.maximal.diagnostics["n_forced_heads"] == 1.0
    assert plain.maximal.diagnostics["n_forced_heads"] == 0.0


def test_the_minimal_map_receives_it_too_and_the_maximal_trace_still_contains_it() -> None:
    maps = network_maps_from_run(
        _run_ctx__heads_maps(build_bench(), dam_foot_cells={"reservoir": DAM_FOOT}),
        _output(map={"permanent": "data.hydrography", "calibrate_on": "permanent"}),
    )

    assert maps.minimal is not None and maps.minimal.heads is not None
    assert maps.minimal.heads.forced_cell.tolist() == [DAM_FOOT]
    assert maps.minimal.observed[DAM_FOOT]
    assert not (maps.minimal.observed & ~maps.maximal.observed).any()


def test_a_model_without_a_dam_foot_draws_as_before() -> None:
    assert dam_foot_cells_of_model(SimpleNamespace(dam_foot_cells={})).size == 0
    assert dam_foot_cells_of_model(
        SimpleNamespace(dam_foot_cells={"b": 9, "a": 4, "c": 9})
    ).tolist() == [4, 9]


# From test_the_maximal_heads_map_contains_the_minimal_trace.py
# Under the heads rule the maximal map is traced from the heads of both maps.
#
# The maximal map contains the minimal one by definition. Two files that
# disagree are scored on their union, and the gap is published. On the V-valley
# bench the full network starts on row 12 and the permanent one on row 4, which
# the full network does not draw: the maximal map is then the axis from row 4,
# and ``frac_minimal_outside_maximal`` is the share of the permanent trace the
# full network's own heads miss, rows 4 to 11.


def _axis(first_row: int) -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[cell_id(row, AXIS_COL) for row in range(first_row, N_ROWS)]] = True
    return mask


def test_the_maximal_heads_map_contains_the_minimal_trace() -> None:
    output = validate_calib_output(
        {
            "support": "network",
            "map": {
                "complete": "data.hydrography",
                "permanent": "data.hydrography",
                "drawn_by": "heads",
                "heads": {"min_drained_area": 0.0},
                "calibrate_on": "permanent",
            },
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
        }
    )

    maps = network_maps_from_run(_run_ctx__heads_maps(build_bench()), output)

    assert maps.minimal is not None
    np.testing.assert_array_equal(maps.minimal.observed, _axis(PERMANENT_FIRST_ROW))
    np.testing.assert_array_equal(maps.maximal.observed, _axis(PERMANENT_FIRST_ROW))
    assert maps.frac_minimal_outside_maximal == pytest.approx(
        (FIRST_OBSERVED_ROW - PERMANENT_FIRST_ROW) / (N_ROWS - PERMANENT_FIRST_ROW)
    )

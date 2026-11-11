"""What the stream criterion reads once, for a trial and for a figure drawn from the run.

The cells a mapped line draws, the free ends of the lines, the cells of the catchment
outline, the reference the basin is compared to, the snapped outlet and the mean
recharge each have one function. The cases below are the ones both callers rely on.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.model.forcing.recharge_rates import criterion_mean_recharge
from hydromodpy.results.derive.stream.criterion_inputs import (
    basin_reference,
    catchment_cells,
    criterion_recharge_of_run,
    declared_crs,
    map_heads,
    mapped_cells,
    snapped_outlet,
)
from hydromodpy.results.run.descent import StoredBasin
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests._helpers.ugrid_meshes import quad_mesh

CRS = "EPSG:2154"
ROWS, COLUMNS, CELL = 3, 4, 100.0
N_CELLS = ROWS * COLUMNS


def _grid():
    vertices, faces = quad_mesh(ROWS, COLUMNS, cell_size=CELL)
    polygons = cell_polygons(vertices, faces)
    centres = np.asarray(
        [
            [(column + 0.5) * CELL, (row + 0.5) * CELL]
            for row in range(ROWS)
            for column in range(COLUMNS)
        ]
    )
    return vertices, faces, polygons, centres


def _cells(mask: np.ndarray) -> list[int]:
    return np.flatnonzero(mask).tolist()


def _draw(rule: str, line: LineString, *, centres=True):
    vertices, faces, polygons, grid_centres = _grid()
    return mapped_cells(
        rule,
        [line],
        polygons=polygons,
        vertices=vertices,
        connectivity=faces,
        centres=grid_centres if centres else None,
        mesh_crs=CRS,
        geometry_crs=CRS,
    )


# --- the cells a line draws ----------------------------------------------------------
INSIDE_COLUMN_ONE = LineString([(1.5 * CELL, 0.1 * CELL), (1.5 * CELL, 2.9 * CELL)])
ALONG_AN_EDGE = LineString([(2.0 * CELL, 0.1 * CELL), (2.0 * CELL, 2.9 * CELL)])


@pytest.mark.parametrize(
    ("rule", "line", "expected"),
    [
        ("crossing", INSIDE_COLUMN_ONE, [1, 5, 9]),
        ("touch", INSIDE_COLUMN_ONE, [1, 5, 9]),
        ("touch", ALONG_AN_EDGE, [1, 2, 5, 6, 9, 10]),
    ],
    ids=["crossing in a column", "touch in a column", "touch along an edge"],
)
def test_a_line_draws_the_cells_its_rule_keeps(rule, line, expected) -> None:
    drawn = _draw(rule, line)

    assert drawn.mask.dtype == bool
    assert _cells(drawn.mask) == expected


def test_the_crossing_rule_counts_the_reaches_it_could_not_place() -> None:
    off_the_mesh = LineString([(10 * CELL, 0.0), (10 * CELL, CELL)])

    drawn = _draw("crossing", off_the_mesh)

    assert not drawn.mask.any()
    assert drawn.n_outside_parts == 1


def test_the_touch_rule_has_no_fallback_or_unplaced_reach() -> None:
    drawn = _draw("touch", INSIDE_COLUMN_ONE, centres=False)

    assert (drawn.n_fallback_parts, drawn.n_outside_parts) == (0, 0)


def test_the_heads_rule_has_no_cell_projection() -> None:
    with pytest.raises(ValueError, match="criterion graph"):
        _draw("heads", INSIDE_COLUMN_ONE)


def test_an_unknown_rule_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="'crossing' or 'touch', got 'bresenham'"):
        _draw("bresenham", INSIDE_COLUMN_ONE)


def test_the_crossing_rule_needs_the_centers_it_joins() -> None:
    with pytest.raises(ValueError, match="joins cell centers"):
        _draw("crossing", INSIDE_COLUMN_ONE, centres=False)


# --- the free ends of a line ---------------------------------------------------------
def test_the_free_ends_of_a_line_are_its_heads() -> None:
    candidates = map_heads([INSIDE_COLUMN_ONE], mesh_crs=CRS, geometry_crs=CRS)

    assert candidates.n_candidates == 2
    assert candidates.forced_cells.size == 0
    assert candidates.n_cut_ends == 0


def test_the_foot_of_a_dam_is_a_head_of_its_own() -> None:
    candidates = map_heads([INSIDE_COLUMN_ONE], mesh_crs=CRS, geometry_crs=CRS, dam_foot=[9, 5, 9])

    assert candidates.forced_cells.tolist() == [5, 9]


def test_the_outlet_changes_no_head() -> None:
    plain = map_heads([INSIDE_COLUMN_ONE], mesh_crs=CRS, geometry_crs=CRS)
    placed = map_heads(
        [INSIDE_COLUMN_ONE], mesh_crs=CRS, geometry_crs=CRS, outlet_xy=(1.5 * CELL, 0.1 * CELL)
    )

    np.testing.assert_array_equal(plain.head_xy, placed.head_xy)
    np.testing.assert_array_equal(plain.reach_end_xy, placed.reach_end_xy)


def test_an_end_the_cut_made_is_no_head() -> None:
    cut = box(0.0, 1.0 * CELL, COLUMNS * CELL, 2.9 * CELL + 1.0)
    along = LineString([(1.5 * CELL, 1.0 * CELL), (1.5 * CELL, 2.9 * CELL)])

    candidates = map_heads([along], mesh_crs=CRS, geometry_crs=CRS, cut_outline=cut, cut_crs=CRS)

    assert candidates.n_cut_ends == 1
    assert candidates.n_candidates == 1


# --- the snapped outlet --------------------------------------------------------------
@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (3.0, 4.0, (3.0, 4.0)),
        ("150.5", "20", (150.5, 20.0)),
        (None, None, None),
        (3.0, None, None),
        ("not a number", 4.0, None),
        (float("nan"), 4.0, None),
        (3.0, float("inf"), None),
    ],
    ids=["numbers", "strings", "none", "one none", "text", "nan", "inf"],
)
def test_the_snapped_outlet_is_a_finite_point_or_none(x, y, expected) -> None:
    assert snapped_outlet(x, y) == expected


@pytest.mark.parametrize(
    ("geographic", "expected"),
    [
        (SimpleNamespace(crs_project="EPSG:2154"), "EPSG:2154"),
        (SimpleNamespace(crs_proj="EPSG:32631"), "EPSG:32631"),
        (SimpleNamespace(crs_project=None, crs_proj="EPSG:32631"), "EPSG:32631"),
        (SimpleNamespace(), None),
        (None, None),
    ],
    ids=["project", "proj", "project missing", "none declared", "no geographic"],
)
def test_the_declared_crs_is_the_projected_one(geographic, expected) -> None:
    assert declared_crs(geographic) == expected


# --- the cells of the outline --------------------------------------------------------
def _outline(*boxes) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=list(boxes), crs=CRS)


def test_a_cell_belongs_to_the_outline_when_its_center_is_inside() -> None:
    _, _, polygons, _ = _grid()
    # Column 1 is cut by the outline, but its center is outside it.
    outline = _outline(box(0.0, 0.0, 1.4 * CELL, ROWS * CELL))

    mask = catchment_cells(polygons, outline, mesh_crs=CRS)

    assert _cells(mask) == [0, 4, 8]


def test_the_outline_cells_keep_the_cells_whose_center_it_covers_and_no_ring() -> None:
    _, _, polygons, _ = _grid()
    outline = _outline(box(0.0, 0.0, 2.2 * CELL, ROWS * CELL))

    mask = catchment_cells(polygons, outline, mesh_crs=CRS)

    # The cells of column 2 are cut by the outline but their centers lie outside.
    assert _cells(mask) == [0, 1, 4, 5, 8, 9]


@pytest.mark.parametrize(
    "outline",
    [None, gpd.GeoDataFrame(geometry=[], crs=CRS)],
    ids=["no outline", "empty outline"],
)
def test_no_outline_gives_no_cells(outline) -> None:
    _, _, polygons, _ = _grid()

    assert catchment_cells(polygons, outline, mesh_crs=CRS) is None


def test_an_outline_without_a_mesh_crs_gives_no_cells() -> None:
    _, _, polygons, _ = _grid()

    assert catchment_cells(polygons, _outline(box(0, 0, 100, 100)), mesh_crs=None) is None


# --- the reference of basin_mismatch -------------------------------------------------
NO_BASIN = (
    "Network criterion: run sim-x carries no basin of D, so the catchment mismatch is "
    "measured against the old reference 'polygon_centroid'."
)
OUTLINE = np.array([False, True, True, False])


def _basin(mask, rule: str = "near_point") -> StoredBasin:
    return StoredBasin(mask=np.asarray(mask), area_m2=float(np.sum(mask)) * CELL**2, rule=rule)


def test_the_basin_of_the_catchment_is_the_reference_and_is_a_copy(caplog) -> None:
    basin = _basin([True, True, False, False])

    with caplog.at_level(logging.INFO):
        reference = basin_reference(basin, OUTLINE, source="run sim-x")
    reference[:] = False

    assert basin.mask.any()
    assert "carries no basin" not in caplog.text


def test_a_stored_mask_of_integers_comes_back_as_booleans() -> None:
    basin = _basin(np.array([1, 0, 1], dtype=np.int8))

    reference = basin_reference(basin, None, source="run sim-x")

    assert reference.dtype == bool
    assert reference.tolist() == [True, False, True]


def test_without_a_basin_the_reference_is_the_outline_and_it_is_said_once(caplog) -> None:
    with caplog.at_level(logging.INFO):
        reference = basin_reference(None, OUTLINE, source="run sim-x")

    np.testing.assert_array_equal(reference, OUTLINE)
    messages = [r for r in caplog.records if r.getMessage() == NO_BASIN]
    assert len(messages) == 1
    assert messages[0].levelno == logging.WARNING


def test_a_backend_that_builds_no_d_only_informs(caplog) -> None:
    with caplog.at_level(logging.INFO):
        basin_reference(None, OUTLINE, source="run sim-x", builds_d=False)

    record = next(r for r in caplog.records if r.getMessage() == NO_BASIN)
    assert record.levelno == logging.INFO


def test_the_largest_basin_of_a_synthetic_domain_is_no_catchment(caplog) -> None:
    with caplog.at_level(logging.INFO):
        reference = basin_reference(
            _basin([True, True, True, True], rule="largest_basin"), OUTLINE, source="run sim-x"
        )

    np.testing.assert_array_equal(reference, OUTLINE)
    assert "carries no basin" not in caplog.text


@pytest.mark.parametrize("basin", [None, _basin([True, True], rule="largest_basin")])
def test_a_domain_with_neither_basin_nor_outline_has_no_reference(basin, caplog) -> None:
    with caplog.at_level(logging.INFO):
        assert basin_reference(basin, None, source="run sim-x") is None

    assert "carries no basin" not in caplog.text


# --- the mean recharge ---------------------------------------------------------------
# One rule, three sources, in the order a figure used to try them: the model its
# trials built, then the station forcing the run stores on its period edges, then the
# recharge budget the solver wrote. The order is part of the number: on the monthly
# Nancon the budget gave 8.634e-9 m/s where the model gave 9.062e-9.
MM_PER_DAY = 1.0e-3 / 86400.0
FORCING_MM_D = pd.Series(
    [2.09, 0.76, 0.5], index=pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
)
EDGES = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])
RATES_M_S = FORCING_MM_D.to_numpy() * MM_PER_DAY
PERIOD_DAYS = np.array([31.0, 29.0, 31.0])
FORCING_MEAN_M_S = float(np.average(RATES_M_S, weights=PERIOD_DAYS))
CELL_AREA = CELL * CELL
MESH = SimpleNamespace(cell_areas=lambda: np.full(N_CELLS, CELL_AREA))


def _store(tmp_path, *, forcing=None, budget=None, stamps=None):
    """A field store with a station forcing and a recharge budget, either or none."""
    path = tmp_path / "fields.zarr"
    SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1).close()
    writer = SimulationZarr(path)
    if forcing is not None:
        writer.write_forcing_timeseries(
            "recharge", "STATION", forcing.index.values, forcing.to_numpy(), unit="mm/day"
        )
    if stamps is not None:
        seconds = stamps.to_numpy(dtype="datetime64[s]").astype("int64").astype(float)
        writer.write_time(seconds, units="seconds since 1970-01-01")
    if budget is not None:
        writer.write_field_stack("recharge", budget, subgroup="budget")
    writer.close()
    return SimulationZarr(path)


def _budget(rates_m_s, *, layers: int = 0) -> np.ndarray:
    """The cell recharge, in m3/s, of one rate per period, in the layout the solver writes."""
    stack = np.stack([np.full(N_CELLS, rate * CELL_AREA) for rate in rates_m_s])
    if layers:
        zeros = np.zeros_like(stack)
        return np.stack([stack, *([zeros] * (layers - 1))], axis=1)
    return stack


def test_the_built_model_gives_the_number_its_trials_read(tmp_path) -> None:
    model = SimpleNamespace(recharge=pd.Series([4.0e-9]))
    fields = _store(tmp_path, forcing=FORCING_MM_D)

    assert criterion_recharge_of_run(model, fields, EDGES) == pytest.approx(4.0e-9, rel=1e-12)


def test_a_model_that_holds_no_finite_rate_falls_through_to_the_forcing(tmp_path) -> None:
    model = SimpleNamespace(recharge=pd.Series([np.nan]))
    fields = _store(tmp_path, forcing=FORCING_MM_D)

    recharge = criterion_recharge_of_run(model, fields, EDGES)

    assert recharge == pytest.approx(FORCING_MEAN_M_S, rel=1e-9)


def test_a_station_forced_run_reads_the_forcing_on_its_edges(tmp_path) -> None:
    fields = _store(tmp_path, forcing=FORCING_MM_D)

    recharge = criterion_recharge_of_run(SimpleNamespace(), fields, EDGES)

    assert recharge == pytest.approx(FORCING_MEAN_M_S, rel=1e-9)


def test_another_window_gives_another_number(tmp_path) -> None:
    fields = _store(tmp_path, forcing=FORCING_MM_D)

    shifted = criterion_recharge_of_run(SimpleNamespace(), fields, EDGES[1:])

    assert shifted != pytest.approx(FORCING_MEAN_M_S, rel=1e-3)


def test_other_data_gives_another_number(tmp_path) -> None:
    fields = _store(tmp_path, forcing=FORCING_MM_D * 0.8)

    recharge = criterion_recharge_of_run(SimpleNamespace(), fields, EDGES)

    assert recharge == pytest.approx(0.8 * FORCING_MEAN_M_S, rel=1e-9)


def test_stations_are_averaged_before_the_periods(tmp_path) -> None:
    fields = _store(tmp_path, forcing=FORCING_MM_D)
    with SimulationZarr(fields.path) as writer:
        writer.write_forcing_timeseries(
            "recharge",
            "SECOND",
            FORCING_MM_D.index.values,
            FORCING_MM_D.to_numpy() * 3.0,
            unit="mm/day",
        )

    recharge = criterion_recharge_of_run(SimpleNamespace(), SimulationZarr(fields.path), EDGES)

    assert recharge == pytest.approx(2.0 * FORCING_MEAN_M_S, rel=1e-9)


def test_a_forcing_with_no_dates_to_place_it_on_is_not_a_source(tmp_path) -> None:
    fields = _store(tmp_path, forcing=FORCING_MM_D)

    assert criterion_recharge_of_run(SimpleNamespace(), fields, None) is None


def test_a_run_without_a_stored_forcing_reads_its_budget(tmp_path) -> None:
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01", "2000-04-01"])
    fields = _store(tmp_path, budget=_budget(RATES_M_S), stamps=stamps)
    model = SimpleNamespace(solver_mesh=MESH)

    recharge = criterion_recharge_of_run(model, fields, EDGES)

    assert recharge == pytest.approx(FORCING_MEAN_M_S, rel=1e-3)


def test_the_budget_counts_every_timestep_by_its_length_not_the_last_alone(tmp_path) -> None:
    rates = np.array([1.0e-8, 1.0e-8, 7.0e-8])
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01", "2000-04-01"])
    fields = _store(tmp_path, budget=_budget(rates), stamps=stamps)

    recharge = criterion_recharge_of_run(SimpleNamespace(solver_mesh=MESH), fields, EDGES)

    assert recharge == pytest.approx(np.average(rates, weights=PERIOD_DAYS), rel=1e-3)
    assert recharge != pytest.approx(rates[-1], rel=1e-2)


def test_a_budget_without_dates_counts_each_step_once(tmp_path) -> None:
    rates = np.array([1.0e-8, 3.0e-8])
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01"])
    fields = _store(tmp_path, budget=_budget(rates), stamps=stamps)

    recharge = criterion_recharge_of_run(SimpleNamespace(solver_mesh=MESH), fields, None)

    assert recharge == pytest.approx(2.0e-8, rel=1e-3)


def test_recharge_split_over_two_layers_scores_the_same_number(tmp_path) -> None:
    rates = np.array([1.0e-8, 3.0e-8])
    stamps = pd.DatetimeIndex(["2000-02-01", "2000-03-01"])
    model = SimpleNamespace(solver_mesh=MESH)
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    single = _store(tmp_path / "one", budget=_budget(rates)[:, None, :], stamps=stamps)
    layered = _store(tmp_path / "two", budget=_budget(rates, layers=2), stamps=stamps)

    assert criterion_recharge_of_run(model, layered, None) == pytest.approx(
        criterion_recharge_of_run(model, single, None), rel=1e-12
    )


def test_the_rule_is_the_one_mean_of_recharge_rates() -> None:
    assert criterion_mean_recharge([np.array([1.0, np.nan]), 3.0]) == 2.0


def test_a_run_with_no_source_gives_none(tmp_path) -> None:
    fields = _store(tmp_path)

    assert criterion_recharge_of_run(SimpleNamespace(), fields, EDGES) is None
    assert criterion_recharge_of_run(SimpleNamespace(solver_mesh=MESH), fields, EDGES) is None

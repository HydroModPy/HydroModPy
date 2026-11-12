"""What the stream criterion reads once, for a trial and for a figure drawn from the run.

The cells a mapped line draws, the free ends of the lines, the cells of the catchment
outline, the reference the basin is compared to, the snapped outlet and the mean
recharge each have one function. The cases below are the ones both callers rely on.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from hydromodpy.mesh.planar.geometry import cell_polygons
from hydromodpy.results.derive.stream_network.criterion_inputs import (
    criterion_recharge_of_run,
    map_heads,
    mapped_cells,
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


def test_an_end_the_cut_made_is_no_head() -> None:
    cut = box(0.0, 1.0 * CELL, COLUMNS * CELL, 2.9 * CELL + 1.0)
    along = LineString([(1.5 * CELL, 1.0 * CELL), (1.5 * CELL, 2.9 * CELL)])

    candidates = map_heads([along], mesh_crs=CRS, geometry_crs=CRS, cut_outline=cut, cut_crs=CRS)

    assert candidates.n_cut_ends == 1
    assert candidates.n_candidates == 1


# --- the snapped outlet --------------------------------------------------------------


# --- the cells of the outline --------------------------------------------------------
def _outline(*boxes) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=list(boxes), crs=CRS)


# --- the reference of basin_mismatch -------------------------------------------------
NO_BASIN = (
    "Network criterion: run sim-x carries no basin of D, so the catchment mismatch is "
    "measured against the old reference 'polygon_centroid'."
)
OUTLINE = np.array([False, True, True, False])


def _basin(mask, rule: str = "near_point") -> StoredBasin:
    return StoredBasin(mask=np.asarray(mask), area_m2=float(np.sum(mask)) * CELL**2, rule=rule)


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


def test_a_run_with_no_source_gives_none(tmp_path) -> None:
    fields = _store(tmp_path)

    assert criterion_recharge_of_run(SimpleNamespace(), fields, EDGES) is None
    assert criterion_recharge_of_run(SimpleNamespace(solver_mesh=MESH), fields, EDGES) is None

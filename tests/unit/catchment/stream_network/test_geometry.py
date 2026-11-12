"""The geometry of the stream-network criterion: its surface, its lengths and its console warnings.

The criterion reads its surface, its outlet and its catchment on one graph (the
model top flooded from the border of the active domain). ``h_obs`` is the cell
size on the mapped network, the Eq. 4 bound is a length (``D_optim <=
validity_length``), and the two warnings a build prints are told once, not at
every build of a calibration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy
from hydromodpy.catchment.drainage.distance import (
    CATCHMENT_MISMATCH_WARNING_SHARE,
    downslope_distance_to_mask,
    longest_descent_length,
    resolve_outlet,
)
from hydromodpy.catchment.stream_network import geometry as stream_geometry
from hydromodpy.catchment.stream_network.geometry import (
    build_network_geometry,
    observed_cell_size_m,
    open_water_mask,
    recharge_session,
    resolve_validity_length,
    share_outside,
)
from hydromodpy.catchment.stream_network.network import downstream_closure
from tests._helpers import v_valley
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import build_bench, observed_network

N_ROWS = 12
N_COLS = 16
N_CELLS = N_ROWS * N_COLS
CELL = 10.0
AXIS = 11
RIDGE = 5
BUFFER_AXIS_ROW = 6


def _cell(row: int, col: int) -> int:
    return row * N_COLS + col


def _columns(first: int, last: int) -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    for row in range(N_ROWS):
        for col in range(first, last + 1):
            mask[_cell(row, col)] = True
    return mask


def _topography() -> np.ndarray:
    rows = np.arange(N_ROWS, dtype=float)[:, None]
    cols = np.arange(N_COLS, dtype=float)[None, :]
    buffer = 120.0 + cols + 2.0 * np.abs(rows - BUFFER_AXIS_ROW)
    ridge = 150.0 + rows + 0.0 * cols
    catchment = 100.0 + rows + 2.0 * np.abs(cols - AXIS)
    surface = np.where(cols < RIDGE, buffer, np.where(cols == RIDGE, ridge, catchment))
    return surface.reshape(-1)


def _observed() -> np.ndarray:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[_cell(row, AXIS) for row in range(N_ROWS)]] = True
    return mask


def _centre(row: int, col: int) -> tuple[float, float]:
    return ((col + 0.5) * CELL, (row + 0.5) * CELL)


def _geometry(**kwargs):
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL)
    kwargs.setdefault("delineated_catchment", _columns(RIDGE, N_COLS - 1))
    return build_network_geometry(
        topography=_topography(),
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=_observed(),
        cell_area_m2=np.full(N_CELLS, CELL * CELL),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
        diagonal_neighbors=True,
        **kwargs,
    )


def test_buffer_stays_out() -> None:
    geometry = _geometry()
    # The buffer used to be raised to the ridge so it could spill into the
    # catchment. Nothing needs raising once the border is an outlet.
    assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))
    assert geometry.frac_reachable_obs_raw == pytest.approx(1.0)


def test_resolve_outlet_asks_for_the_graph_it_snaps_on() -> None:
    geometry = _geometry()
    with pytest.raises(ValueError, match="adjacency"):
        resolve_outlet(geometry.metric, near=_centre(0, AXIS))


def test_polygon_matching_the_graph_reads_zero(caplog) -> None:
    with caplog.at_level("WARNING"):
        geometry = _geometry()

    assert geometry.catchment_mismatch == pytest.approx(0.0)
    assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(0.0)
    assert "differs from the delineated polygon" not in caplog.text


def test_polygon_gap_is_a_share_of_its_area(caplog) -> None:
    # The polygon stops short of the ridge column: twelve cells of the
    # graph catchment lie outside it, over a polygon of 120 cells.
    with caplog.at_level("WARNING"):
        geometry = _geometry(delineated_catchment=_columns(RIDGE + 1, N_COLS - 1))

    assert geometry.catchment_mismatch == pytest.approx(12.0 / 120.0)
    assert geometry.catchment_mismatch > CATCHMENT_MISMATCH_WARNING_SHARE
    assert "differs from the delineated polygon by 10.0%" in caplog.text


def test_no_polygon_gives_no_gap() -> None:
    geometry = _geometry(delineated_catchment=None, delineated_outlet_xy=_centre(0, AXIS))

    assert np.isnan(geometry.catchment_mismatch)
    assert geometry.outlet == _cell(0, AXIS)


def _valley(n_rows: int, n_cols: int, axis: int) -> np.ndarray:
    rows = np.arange(n_rows)[:, None]
    cols = np.arange(n_cols)[None, :]
    return (1000.0 - rows + 2.0 * np.abs(cols - axis)).reshape(-1)


def _axis(n_rows: int, n_cols: int, axis: int) -> np.ndarray:
    mask = np.zeros(n_rows * n_cols, dtype=bool)
    mask[np.arange(n_rows) * n_cols + axis] = True
    return mask


def _rectilinear(x_edges: np.ndarray, y_edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, connectivity) of a grid with the given column and row edges."""
    n_cols, n_rows = x_edges.size - 1, y_edges.size - 1
    xx, yy = np.meshgrid(x_edges, y_edges)
    vertices = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    corner = (np.arange(n_rows)[:, None] * (n_cols + 1) + np.arange(n_cols)[None, :]).reshape(-1)
    connectivity = np.column_stack([corner, corner + 1, corner + n_cols + 2, corner + n_cols + 1])
    return vertices, connectivity


@pytest.mark.parametrize("cell", [10.0, 75.0])
def test_h_obs_on_a_regular_grid(cell: float) -> None:
    n_rows, n_cols, axis = 30, 21, 10
    vertices, connectivity = quad_mesh(n_rows, n_cols, cell_size=cell)
    areas = np.full(n_rows * n_cols, cell * cell)
    geometry = build_network_geometry(
        topography=_valley(n_rows, n_cols, axis),
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=_axis(n_rows, n_cols, axis),
        cell_area_m2=areas,
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
    )
    # The former L_ref, the square root of the median cell area of the catchment.
    former = float(np.sqrt(np.median(areas[geometry.catchment])))

    assert geometry.h_obs_m == pytest.approx(former)
    assert geometry.h_obs_m == pytest.approx(cell)
    assert geometry.validity_length().length_m == pytest.approx(2.0 * cell)


def test_h_obs_on_a_refined_stream() -> None:
    # Three columns 10 m wide around the axis, 30 m wide elsewhere, rows of 10 m.
    widths = np.array([30.0] * 9 + [10.0] * 3 + [30.0] * 9)
    x_edges = np.concatenate([[0.0], np.cumsum(widths)])
    n_rows, n_cols, axis = 30, widths.size, 10
    y_edges = np.arange(n_rows + 1) * 10.0
    vertices, connectivity = _rectilinear(x_edges, y_edges)
    areas = np.tile(widths * 10.0, n_rows)
    geometry = build_network_geometry(
        topography=_valley(n_rows, n_cols, axis),
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=_axis(n_rows, n_cols, axis),
        cell_area_m2=areas,
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
    )
    median_cell = float(np.sqrt(np.median(areas[geometry.catchment])))

    assert geometry.h_obs_m == pytest.approx(10.0)
    assert geometry.validity_length().length_m == pytest.approx(20.0)
    assert median_cell == pytest.approx(np.sqrt(300.0))


def test_declared_accuracy_widens_the_validity_length() -> None:
    n_rows, n_cols, axis = 30, 21, 10
    vertices, connectivity = quad_mesh(n_rows, n_cols, cell_size=10.0)
    geometry = build_network_geometry(
        topography=_valley(n_rows, n_cols, axis),
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=_axis(n_rows, n_cols, axis),
        cell_area_m2=np.full(n_rows * n_cols, 100.0),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
        observed_position_accuracy_m=25.0,
    )

    assert geometry.h_obs_m == pytest.approx(10.0)
    validity = geometry.validity_length()
    assert validity.length_m == pytest.approx(50.0)
    assert validity.provenance == "declared_accuracy"
    # A declared length wins over everything the map says.
    assert geometry.validity_length(300.0).length_m == pytest.approx(300.0)
    assert geometry.validity_length(300.0).provenance == "user"


def test_cell_size_without_a_mapped_cell() -> None:
    vertices, connectivity = quad_mesh(3, 3, cell_size=20.0)
    centres = vertices[connectivity].mean(axis=1)[:, :2]
    none = np.zeros(9, dtype=bool)

    assert observed_cell_size_m(
        centres, connectivity, observed=none, catchment=np.ones(9, dtype=bool)
    ) == pytest.approx(20.0)


@pytest.mark.parametrize(
    ("h_obs", "accuracy", "length", "provenance"),
    [
        (75.0, None, 150.0, "auto"),
        (25.0, 50.0, 100.0, "declared_accuracy"),
        (75.0, 50.0, 150.0, "auto"),
    ],
)
def test_auto_validity_length(
    h_obs: float, accuracy: float | None, length: float, provenance: str
) -> None:
    validity = resolve_validity_length(h_obs_m=h_obs, accuracy_m=accuracy)

    assert validity.length_m == pytest.approx(length)
    assert validity.provenance == provenance


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test starts as a new process: no recharge seen, no alpha warned."""
    monkeypatch.setattr(stream_geometry, "_last_mean_recharge", {})
    monkeypatch.setattr(stream_geometry, "_alpha_warned", False)


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_recharge_move_warns(caplog) -> None:
    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("s"),
    ):
        stream_geometry._warn_if_recharge_moved(9.074854999999997e-09)
        stream_geometry._warn_if_recharge_moved(8.655624187444443e-09)

    (message,) = _warnings(caplog)
    assert "9.075e-09 then 8.656e-09 m/s" in message


# The scored cells, the share of a map outside another one and the open-water mask
# are one definition of "what the criterion scores", read by the trial and by the
# figure drawn from the run. The geometry is a stand-in holding the three masks the
# definition reads.
def _scored_geometry(catchment, active, excluded=None) -> SimpleNamespace:
    return SimpleNamespace(
        catchment=np.asarray(catchment, dtype=bool),
        metric=SimpleNamespace(graph=SimpleNamespace(active=np.asarray(active, dtype=bool))),
        excluded=None if excluded is None else np.asarray(excluded, dtype=bool),
    )


@pytest.mark.parametrize(
    ("inner", "outer", "geometry", "expected"),
    [
        ([1, 1, 1, 0], [1, 0, 0, 0], _scored_geometry([1, 1, 1, 1], [1] * 4), 2 / 3),
        ([1, 1, 1, 0], [1, 1, 1, 0], _scored_geometry([1, 1, 1, 1], [1] * 4), 0.0),
        # A cell off the catchment is not counted in either term.
        ([1, 1, 1, 0], [1, 0, 0, 0], _scored_geometry([1, 1, 0, 0], [1] * 4), 0.5),
        # Open water leaves the support: the missed cell goes, the share moves.
        ([1, 1, 1, 0], [1, 0, 1, 0], _scored_geometry([1] * 4, [1] * 4, [0, 1, 0, 0]), 0.0),
        # An inactive cell leaves it too.
        ([1, 1, 1, 0], [1, 0, 1, 0], _scored_geometry([1] * 4, [1, 0, 1, 1]), 0.0),
        ([1, 1, 1, 0], [1, 0, 0, 0], _scored_geometry([0] * 4, [1] * 4), float("nan")),
        # An empty map has no cell to miss.
        ([0, 0, 0, 0], [1, 0, 0, 0], _scored_geometry([1] * 4, [1] * 4), float("nan")),
    ],
    ids=[
        "two of three missed",
        "none missed",
        "off the catchment",
        "open water",
        "inactive cell",
        "no scored cell",
        "empty map",
    ],
)
def test_share_a_map_misses(inner, outer, geometry, expected) -> None:
    share = share_outside(np.array(inner, dtype=bool), np.array(outer, dtype=bool), geometry)

    if np.isnan(expected):
        assert np.isnan(share)
    else:
        assert share == pytest.approx(expected)


def test_open_water_moves_the_share() -> None:
    n_cells = 1200
    inner = np.zeros(n_cells, dtype=bool)
    inner[:100] = True
    outer = np.zeros(n_cells, dtype=bool)
    outer[:30] = True
    lake = np.zeros(n_cells, dtype=bool)
    lake[60:72] = True
    everywhere = _scored_geometry(np.ones(n_cells), np.ones(n_cells))
    off_the_lake = _scored_geometry(np.ones(n_cells), np.ones(n_cells), lake)

    assert share_outside(inner, outer, everywhere) == pytest.approx(0.7)
    assert share_outside(inner, outer, off_the_lake) == pytest.approx(58 / 88)


# The V-valley bench of tests/_helpers/v_valley, which the cost tests use too.
BENCH_ROWS = v_valley.N_ROWS
BENCH_COLS = v_valley.N_COLS
BENCH_CELLS = v_valley.N_CELLS
BENCH_CELL_M = v_valley.CELL_SIZE
BENCH_AXIS = v_valley.AXIS_COL
FIRST_DIVIDED_ROW = 20


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _bench_geometry(topography, **kwargs):
    """The criterion geometry of the bench mesh, observed network aligned unless given."""
    vertices, connectivity = quad_mesh(BENCH_ROWS, BENCH_COLS, cell_size=BENCH_CELL_M)
    kwargs.setdefault("observed", observed_network("aligned"))
    kwargs.setdefault("mean_recharge_m_s", 3.2e-8)
    kwargs.setdefault("tau_specific_ratio", 1e-2)
    return build_network_geometry(
        topography=topography,
        face_node_connectivity=connectivity,
        vertices=vertices,
        cell_area_m2=np.full(BENCH_CELLS, BENCH_CELL_M * BENCH_CELL_M),
        **kwargs,
    )


def _divided_valley(first_row: int) -> np.ndarray:
    """The V valley with a divide between ``first_row - 1`` and ``first_row``.

    The rows above the divide slope north and leave the domain through its
    northern border; the rows below keep the valley and its southern outlet.
    The catchment of that outlet on the graph is therefore rows ``first_row``
    and below, and the rows above are a buffer that does not drain into it.
    """
    rows = np.arange(BENCH_ROWS, dtype=float)[:, None]
    cols = np.arange(BENCH_COLS, dtype=float)[None, :]
    divide = float(first_row) - 0.5
    return (1000.0 - np.abs(rows - divide) + 2.0 * np.abs(cols - BENCH_AXIS)).reshape(-1)


def _rows_from(first_row: int) -> np.ndarray:
    """Every cell of the rows ``first_row`` and below."""
    mask = np.zeros(BENCH_CELLS, dtype=bool)
    mask[first_row * BENCH_COLS :] = True
    return mask


def _to_outlet(geometry) -> tuple[np.ndarray, np.ndarray]:
    outlet_mask = np.zeros(BENCH_CELLS, dtype=bool)
    outlet_mask[geometry.outlet] = True
    return outlet_mask, downslope_distance_to_mask(geometry.metric, outlet_mask)


def test_no_lakes_gives_no_mask() -> None:
    assert open_water_mask([], BENCH_CELLS) is None
    assert open_water_mask(None, BENCH_CELLS) is None


def test_modflow6_builder_writes_the_open_water_attribute() -> None:
    # The defect this guards is invisible at runtime: the criterion reads an
    # attribute, gets None, and reports a plausible number.
    source = (Path(hydromodpy.__file__).parent / "solver" / "modflow6" / "build.py").read_text(
        encoding="utf-8"
    )
    assert "model.open_water_cell_ids = " in source


# The criterion calibrates K/R, so a recharge that moves between two trials
# changes the calibrated quantity without changing any declared parameter.
def test_geometry_publishes_the_recharge_it_used(bench) -> None:
    geometry = _bench_geometry(bench.elevation, mean_recharge_m_s=3.2e-8, diagonal_neighbors=True)
    assert geometry.diagnostics["R_mean_m_s"] == pytest.approx(3.2e-8)
    # The diagnostic is provenance only if it is the number that divided the ratio.
    area = BENCH_CELL_M * BENCH_CELL_M
    applied = float(geometry.threshold_m3_s[0]) / (area * 1e-2)
    assert applied == pytest.approx(geometry.diagnostics["R_mean_m_s"], rel=1e-12)


def test_recharge_that_moves_is_warned_with_both_values(bench, caplog) -> None:
    with recharge_session("one-search"):
        _bench_geometry(bench.elevation, mean_recharge_m_s=3.2e-8, diagonal_neighbors=True)
        caplog.clear()
        with caplog.at_level("WARNING"):
            _bench_geometry(bench.elevation, mean_recharge_m_s=6.4e-8, diagonal_neighbors=True)
    assert "3.2e-08" in caplog.text
    assert "6.4e-08" in caplog.text


# L_cap is a length of the catchment, not of the model domain. The flood is
# seeded on the border of the domain, so a buffer beyond the divide never
# reaches the outlet.
def test_saturation_cap_is_a_catchment_length() -> None:
    geometry = _bench_geometry(
        _divided_valley(FIRST_DIVIDED_ROW), delineated_catchment=_rows_from(FIRST_DIVIDED_ROW)
    )
    outlet_mask, to_outlet = _to_outlet(geometry)

    inside = geometry.catchment & np.isfinite(to_outlet)
    assert inside.any()
    assert geometry.saturation_cap_m == pytest.approx(float(to_outlet[inside].max()))
    assert np.all(to_outlet[inside] <= geometry.saturation_cap_m + 1e-9)


def test_nothing_beyond_the_divide_reaches_the_outlet() -> None:
    geometry = _bench_geometry(
        _divided_valley(FIRST_DIVIDED_ROW), delineated_catchment=_rows_from(FIRST_DIVIDED_ROW)
    )
    outlet_mask, to_outlet = _to_outlet(geometry)

    assert np.array_equal(geometry.catchment, _rows_from(FIRST_DIVIDED_ROW))
    assert not np.any(np.isfinite(to_outlet[~geometry.catchment]))
    assert longest_descent_length(geometry.metric, outlet_mask) == pytest.approx(
        geometry.saturation_cap_m
    )


def test_empty_support_is_refused() -> None:
    geometry = _bench_geometry(
        _divided_valley(FIRST_DIVIDED_ROW), delineated_catchment=_rows_from(FIRST_DIVIDED_ROW)
    )
    outlet_mask, _ = _to_outlet(geometry)
    with pytest.raises(ValueError, match="inside the requested support"):
        longest_descent_length(
            geometry.metric, outlet_mask, within=np.zeros(BENCH_CELLS, dtype=bool)
        )


def test_open_water_stays_out_of_the_reachability_diagnostics(bench) -> None:
    # Otherwise a reservoir absorbing paths would flatter the number that says
    # how well the linework agrees with the routing surface. The lake is off the
    # mapped axis, on the hillside.
    lake = np.zeros(BENCH_CELLS, dtype=bool)
    lake[[v_valley.cell_id(row, 8) for row in range(28, 34)]] = True
    with_lake = _bench_geometry(bench.elevation, excluded=lake, diagonal_neighbors=True)
    without = _bench_geometry(bench.elevation, excluded=None, diagonal_neighbors=True)
    for key in ("frac_reachable_obs_raw", "alpha_obs_closure"):
        assert with_lake.diagnostics[key] == pytest.approx(without.diagnostics[key])


# alpha_obs_closure on the whole mesh answers a different question from the
# scored catchment. A mapped linework is routinely wider than the catchment it
# is used on, and the trace of those reaches inflates the closure without adding
# to the numerator (on the Nancon 0.306 on the mesh against 0.693 on the
# catchment). The bench holds a divide above row FIRST_DIVIDED_ROW: the rows
# north of it drain off the domain.
def _alpha_geometry(bench, catchment, case="aligned", observed=None):
    clipped = not bool(np.all(catchment))
    return _bench_geometry(
        _divided_valley(FIRST_DIVIDED_ROW) if clipped else bench.elevation,
        observed=observed_network(case) if observed is None else observed,
        delineated_catchment=catchment,
    )


@pytest.mark.parametrize("case", ["aligned", "shifted", "hole", "truncated"])
def test_alpha_ratios_are_the_ones_the_masks_hold(bench, case) -> None:
    geometry = _alpha_geometry(bench, _rows_from(FIRST_DIVIDED_ROW), case=case)
    closure = downstream_closure(geometry.metric, geometry.observed)
    inside = closure & geometry.catchment

    assert geometry.alpha_obs_closure == pytest.approx(geometry.observed.sum() / closure.sum())
    assert geometry.alpha_obs_closure_catchment == pytest.approx(
        (geometry.observed & geometry.catchment).sum() / inside.sum()
    )


def test_catchment_holding_the_whole_network_makes_alphas_agree(bench) -> None:
    geometry = _alpha_geometry(bench, np.ones(BENCH_CELLS, dtype=bool))

    assert geometry.frac_obs_outside_catchment == pytest.approx(0.0)
    assert geometry.alpha_obs_closure_catchment == pytest.approx(geometry.alpha_obs_closure)


def test_share_of_the_network_outside_the_catchment(bench) -> None:
    geometry = _alpha_geometry(bench, _rows_from(FIRST_DIVIDED_ROW))

    # Rows 12 to 19 of the axis column are mapped and out of the catchment.
    outside = FIRST_DIVIDED_ROW - v_valley.FIRST_OBSERVED_ROW
    mapped = BENCH_ROWS - v_valley.FIRST_OBSERVED_ROW
    assert geometry.frac_obs_outside_catchment == pytest.approx(outside / mapped)


def test_clipping_that_leaves_alpha_alone_stays_silent(bench, caplog) -> None:
    # The axis is mapped on both sides of the divide, down to the northern
    # border and down to the outlet, so each reach closes on itself.
    observed = np.zeros(BENCH_CELLS, dtype=bool)
    observed[[v_valley.cell_id(row, BENCH_AXIS) for row in range(BENCH_ROWS)]] = True
    with caplog.at_level("WARNING"):
        geometry = _alpha_geometry(bench, _rows_from(FIRST_DIVIDED_ROW), observed=observed)

    # A third of the mapped cells are out, over ground that routes on its
    # own, so both ratios read 1.000 and there is nothing to report.
    assert geometry.frac_obs_outside_catchment > 0.10
    assert geometry.alpha_obs_closure == pytest.approx(1.0)
    assert "outside the scored catchment" not in caplog.text


def test_reach_beyond_the_divide_is_reported(bench, caplog) -> None:
    # Rows 12 to 19 of the axis are mapped beyond the divide and drain north
    # through twelve unmapped cells: that trace alone moves the mesh ratio.
    with caplog.at_level("WARNING"):
        geometry = _alpha_geometry(bench, _rows_from(FIRST_DIVIDED_ROW))

    assert geometry.alpha_obs_closure_catchment == pytest.approx(1.0)
    assert geometry.alpha_obs_closure < 0.9
    assert "outside the scored catchment" in caplog.text

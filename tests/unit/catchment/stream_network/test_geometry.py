"""The geometry of the stream-network criterion: its surface, its lengths and its console warnings.

The criterion reads its surface, its outlet and its catchment on one graph (the
model top flooded from the border of the active domain). ``h_obs`` is the cell
size on the mapped network, the Eq. 4 bound is a length (``D_optim <=
validity_length``), and the two warnings a build prints are told once, not at
every build of a calibration.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.drainage.distance import CATCHMENT_MISMATCH_WARNING_SHARE, resolve_outlet
from hydromodpy.catchment.stream_network import geometry as stream_geometry
from hydromodpy.catchment.stream_network.geometry import (
    build_network_geometry,
    observed_cell_size_m,
    resolve_validity_length,
    share_outside,
)
from tests._helpers.ugrid_meshes import quad_mesh

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


class TestTheBufferStaysOut:
    def test_no_cell_is_raised_on_a_surface_without_a_closed_pit(self) -> None:
        geometry = _geometry()
        # The buffer used to be raised to the ridge so it could spill into the
        # catchment. Nothing needs raising once the border is an outlet.
        assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))
        assert geometry.frac_reachable_obs_raw == pytest.approx(1.0)


class TestTheOutletIsSnappedOnTheGraph:
    def test_resolve_outlet_asks_for_the_graph_it_snaps_on(self) -> None:
        geometry = _geometry()
        with pytest.raises(ValueError, match="adjacency"):
            resolve_outlet(geometry.metric, near=_centre(0, AXIS))


class TestTheGapToThePolygonIsPublished:
    def test_a_polygon_that_matches_the_graph_reads_zero(self, caplog) -> None:
        with caplog.at_level("WARNING"):
            geometry = _geometry()

        assert geometry.catchment_mismatch == pytest.approx(0.0)
        assert geometry.diagnostics["catchment_mismatch"] == pytest.approx(0.0)
        assert "differs from the delineated polygon" not in caplog.text

    def test_the_gap_is_a_share_of_the_polygon_area(self, caplog) -> None:
        # The polygon stops short of the ridge column: twelve cells of the
        # graph catchment lie outside it, over a polygon of 120 cells.
        with caplog.at_level("WARNING"):
            geometry = _geometry(delineated_catchment=_columns(RIDGE + 1, N_COLS - 1))

        assert geometry.catchment_mismatch == pytest.approx(12.0 / 120.0)
        assert geometry.catchment_mismatch > CATCHMENT_MISMATCH_WARNING_SHARE
        assert "differs from the delineated polygon by 10.0%" in caplog.text

    def test_without_a_polygon_the_gap_is_not_a_number(self) -> None:
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
def test_on_a_regular_grid_the_numbers_do_not_move(cell: float) -> None:
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


def test_on_a_mesh_refined_along_the_stream_it_is_the_fine_cell() -> None:
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


def test_a_declared_accuracy_widens_the_validity_length_and_not_h_obs() -> None:
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


def test_a_catchment_without_a_mapped_cell_falls_back_on_the_catchment() -> None:
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
def test_auto_follows_the_cell_and_the_accuracy(
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


def test_a_real_move_warns_with_four_significant_digits(caplog) -> None:
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
def test_the_share_a_map_misses_is_read_on_the_scored_cells(
    inner, outer, geometry, expected
) -> None:
    share = share_outside(np.array(inner, dtype=bool), np.array(outer, dtype=bool), geometry)

    if np.isnan(expected):
        assert np.isnan(share)
    else:
        assert share == pytest.approx(expected)


def test_one_per_cent_of_open_water_moves_the_share_it_used_to_ignore() -> None:
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

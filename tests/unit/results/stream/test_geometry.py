"""The geometry of the stream-network criterion: its surface, its lengths and its console warnings.

The criterion reads its surface, its outlet and its catchment on one graph (the
model top flooded from the border of the active domain). ``h_obs`` is the cell
size on the mapped network, the Eq. 4 bound is a length (``D_optim <=
validity_length``), and the two warnings a build prints are told once, not at
every build of a calibration.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.catchment.drainage.distance import CATCHMENT_MISMATCH_WARNING_SHARE, resolve_outlet
from hydromodpy.results.derive.stream import geometry as stream_geometry
from hydromodpy.results.derive.stream.geometry import (
    VALIDITY_PROVENANCE_BY_CODE,
    VALIDITY_PROVENANCE_CODE,
    build_network_geometry,
    criterion_supports,
    observed_cell_size_m,
    resolve_validity_length,
)
from hydromodpy.results.derive.stream.network import build_simulated_network
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
    def test_the_catchment_is_what_descends_to_the_outlet(self) -> None:
        geometry = _geometry()

        assert geometry.outlet == _cell(0, AXIS)
        assert np.array_equal(geometry.catchment, _columns(RIDGE, N_COLS - 1))

    def test_the_buffer_valley_drains_off_the_domain(self) -> None:
        geometry = _geometry()
        downstream = geometry.metric.graph.downstream

        cell = _cell(BUFFER_AXIS_ROW, 3)
        path = [cell]
        while downstream[path[-1]] >= 0:
            path.append(int(downstream[path[-1]]))
        assert path[-1] == _cell(BUFFER_AXIS_ROW, 0), "the buffer leaves through its border"

    def test_seepage_in_the_buffer_puts_no_stream_in_the_catchment(self) -> None:
        geometry = _geometry()
        release = np.zeros(N_CELLS)
        release[[_cell(BUFFER_AXIS_ROW, col) for col in range(1, RIDGE)]] = 1.0

        simulated = build_simulated_network(
            release, threshold_m3_s=geometry.threshold_m3_s, metric=geometry.metric
        )
        supports = criterion_supports(
            simulated=simulated,
            observed=geometry.observed,
            catchment=geometry.catchment,
            active=geometry.metric.graph.active,
        )

        assert simulated.network.any()
        assert not supports.support_so.any(), "a buffer descent crossed into the catchment"

    def test_no_cell_is_raised_on_a_surface_without_a_closed_pit(self) -> None:
        geometry = _geometry()
        # The buffer used to be raised to the ridge so it could spill into the
        # catchment. Nothing needs raising once the border is an outlet.
        assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))
        assert geometry.frac_reachable_obs_raw == pytest.approx(1.0)

    def test_a_closed_pit_is_still_filled(self) -> None:
        vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL)
        topography = _topography()
        pit = _cell(6, 13)
        topography[pit] -= 20.0
        geometry = build_network_geometry(
            topography=topography,
            face_node_connectivity=connectivity,
            vertices=vertices,
            observed=_observed(),
            cell_area_m2=np.full(N_CELLS, CELL * CELL),
            mean_recharge_m_s=1e-8,
            tau_specific_ratio=0.0,
            delineated_catchment=_columns(RIDGE, N_COLS - 1),
        )

        assert geometry.metric.graph.downstream[pit] >= 0
        assert geometry.catchment[pit]


class TestTheOutletIsSnappedOnTheGraph:
    def test_a_point_one_cell_off_moves_onto_the_most_accumulated_cell(self) -> None:
        geometry = _geometry(delineated_outlet_xy=_centre(1, AXIS + 2))

        assert geometry.outlet == _cell(0, AXIS)

    def test_the_search_stops_two_cells_away(self) -> None:
        geometry = _geometry(delineated_outlet_xy=_centre(0, AXIS + 3))

        assert geometry.outlet != _cell(0, AXIS)
        assert geometry.catchment.sum() < _columns(RIDGE, N_COLS - 1).sum()

    def test_the_point_wins_over_the_polygon(self) -> None:
        # A polygon whose low corner is elsewhere does not move a declared point.
        geometry = _geometry(
            delineated_catchment=_columns(0, RIDGE),
            delineated_outlet_xy=_centre(0, AXIS),
        )

        assert geometry.outlet == _cell(0, AXIS)

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

    def test_a_gap_under_the_threshold_is_not_a_warning(self, caplog) -> None:
        polygon = _columns(RIDGE, N_COLS - 1)
        polygon[_cell(N_ROWS - 1, RIDGE)] = False
        with caplog.at_level("WARNING"):
            geometry = _geometry(delineated_catchment=polygon)

        assert 0.0 < geometry.catchment_mismatch < CATCHMENT_MISMATCH_WARNING_SHARE
        assert "differs from the delineated polygon" not in caplog.text

    def test_without_a_polygon_the_gap_is_not_a_number(self) -> None:
        geometry = _geometry(delineated_catchment=None, delineated_outlet_xy=_centre(0, AXIS))

        assert np.isnan(geometry.catchment_mismatch)
        assert geometry.outlet == _cell(0, AXIS)

    def test_without_a_polygon_or_a_point_the_largest_basin_closes_it_loudly(self, caplog) -> None:
        with caplog.at_level("WARNING"):
            geometry = _geometry(delineated_catchment=None)

        assert geometry.outlet == _cell(0, AXIS)
        assert "no delineated catchment and no outlet" in caplog.text


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


def test_a_declared_length_wins() -> None:
    validity = resolve_validity_length(h_obs_m=25.0, accuracy_m=50.0, declared_m=40.0)

    assert (validity.length_m, validity.provenance) == (40.0, "user")


def test_the_provenance_travels_as_a_code_and_comes_back() -> None:
    for name, code in VALIDITY_PROVENANCE_CODE.items():
        assert VALIDITY_PROVENANCE_BY_CODE[code] == name
    validity = resolve_validity_length(h_obs_m=10.0)
    assert VALIDITY_PROVENANCE_BY_CODE[validity.code] == "auto"


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test starts as a new process: no recharge seen, no alpha warned."""
    monkeypatch.setattr(stream_geometry, "_last_mean_recharge", {})
    monkeypatch.setattr(stream_geometry, "_alpha_warned", False)


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_float_noise_between_two_builds_is_not_a_move(caplog) -> None:
    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("s"),
    ):
        stream_geometry._warn_if_recharge_moved(9.074855002572016e-09)
        stream_geometry._warn_if_recharge_moved(9.074854999999997e-09)

    assert _warnings(caplog) == []


def test_a_real_move_warns_with_four_significant_digits(caplog) -> None:
    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("s"),
    ):
        stream_geometry._warn_if_recharge_moved(9.074854999999997e-09)
        stream_geometry._warn_if_recharge_moved(8.655624187444443e-09)

    (message,) = _warnings(caplog)
    assert "9.075e-09 then 8.656e-09 m/s" in message


def test_a_move_just_above_the_tolerance_still_warns(caplog) -> None:
    base = 1.0e-8
    with (
        caplog.at_level(logging.INFO, logger=stream_geometry.__name__),
        stream_geometry.recharge_session("s"),
    ):
        stream_geometry._warn_if_recharge_moved(base)
        stream_geometry._warn_if_recharge_moved(
            base * (1.0 + 10 * stream_geometry.RECHARGE_MOVE_TOLERANCE)
        )

    assert len(_warnings(caplog)) == 1


def test_builds_outside_a_session_are_never_compared(caplog) -> None:
    """Figures of two runs drawn in one process may hold two forcings."""
    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        stream_geometry._warn_if_recharge_moved(9.0e-09)
        stream_geometry._warn_if_recharge_moved(6.0e-09)

    assert _warnings(caplog) == []


def test_two_sessions_are_not_compared_with_each_other(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        with stream_geometry.recharge_session("first"):
            stream_geometry._warn_if_recharge_moved(9.0e-09)
        with stream_geometry.recharge_session("second"):
            stream_geometry._warn_if_recharge_moved(6.0e-09)
            stream_geometry._warn_if_recharge_moved(6.0e-09)

    assert _warnings(caplog) == []


def test_the_alpha_warning_prints_once_then_goes_to_verbose(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        stream_geometry._report_poor_alpha(0.780, 0.90)
        stream_geometry._report_poor_alpha(0.777, 0.90)
        stream_geometry._report_poor_alpha(0.781, 0.90)

    (message,) = _warnings(caplog)
    assert "alpha_obs_closure_catchment = 0.780, below 0.90" in message
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 2
    assert "0.777" in infos[0].getMessage()


def test_the_alpha_warning_says_it_in_two_sentences(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=stream_geometry.__name__):
        stream_geometry._report_poor_alpha(0.780, 0.90)

    (message,) = _warnings(caplog)
    assert message.count(". ") == 1
    assert message.endswith(".")

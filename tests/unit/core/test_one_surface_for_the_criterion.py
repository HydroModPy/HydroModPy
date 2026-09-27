"""The criterion reads its surface, its outlet and its catchment on one graph.

The model top is flooded from the border of the active domain, the standard
priority flood. The catchment is every cell whose descent reaches the outlet
on that graph, and the raster polygon only places the outlet and measures the
gap. Flooding from the outlet alone declared the whole domain endorheic: a
buffer valley draining off the domain was raised to a col of the divide, and
its seepage then crossed into the catchment down a hillslope that does not
seep (+16 per cent of network cells on the Nancon proxy).

The bench is a 12 x 16 grid. Columns 0 to 4 are a buffer valley draining west
off the domain along row 6; column 5 is a ridge; columns 6 to 15 are the
catchment, a V valley whose axis, column 11, falls to its outlet on row 0.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.stream_geometry import (
    CATCHMENT_MISMATCH_WARNING_SHARE,
    build_network_geometry,
    criterion_supports,
    resolve_outlet,
)
from hydromodpy.core.stream_network import build_simulated_network
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

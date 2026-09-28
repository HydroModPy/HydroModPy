"""``[geographic.snap_streams]`` on a raster grid, before any mesh exists.

The stream burn snaps the mapped network on the conditioned raw DEM. The grid
is read as a structured quad mesh and snapped by the same function as the
criterion. The V valley knows its talweg in closed form: the axis column. A
map shifted by one column comes back on it with a displacement of one cell,
and the network drains to the border of the raster, not to one outlet.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.stream_snap import (
    SNAP_MOVED,
    SnapStreamsConfig,
    grid_quad_mesh,
    snap_observed_network_on_grid,
)
from hydromodpy.core.topographic_distance import build_downslope_metric, shared_node_adjacency

N_ROWS = 41
N_COLS = 31
AXIS = 15
CELL = 25.0
TOP = N_ROWS * CELL


def valley() -> np.ndarray:
    """North-up raster: row 0 is north, water runs south along the axis column."""
    rows = np.arange(N_ROWS)[:, None]
    cols = np.arange(N_COLS)[None, :]
    return (1000.0 - rows + 2.0 * np.abs(cols - AXIS)).astype(float)


def mapped(column: int, first_row: int = 5) -> np.ndarray:
    mask = np.zeros((N_ROWS, N_COLS), dtype=bool)
    mask[first_row:, column] = True
    return mask


def snap(observed: np.ndarray, mode: str = "apply", **kwargs):
    return snap_observed_network_on_grid(
        surface=valley(),
        observed=observed,
        x_origin=0.0,
        y_origin=TOP,
        dx=CELL,
        dy=-CELL,
        settings=SnapStreamsConfig(mode=mode, **kwargs),
    )


def test_the_grid_mesh_numbers_cells_like_the_raster() -> None:
    vertices, faces = grid_quad_mesh((2, 3), x_origin=100.0, y_origin=50.0, dx=10.0, dy=-10.0)
    centre = vertices[faces, :2].mean(axis=1)

    # Cell (1, 2) is face 1 * 3 + 2, centred half a cell into its row and column.
    assert centre[5] == pytest.approx([125.0, 35.0])
    assert faces.shape == (6, 4)


def test_a_shifted_map_comes_back_on_the_axis() -> None:
    result = snap(mapped(AXIS + 1))
    snapped = result.as_grid(result.snap.snapped)

    assert set(np.flatnonzero(snapped.any(axis=0)).tolist()) == {AXIS}
    assert result.snap.displacement_p90_m == pytest.approx(CELL)
    assert result.snap.rejected_share == 0.0
    placed = result.snap.raw & (result.snap.status == SNAP_MOVED)
    assert placed.sum() == result.snap.raw.sum()


def test_a_map_on_the_axis_stays_where_it_is() -> None:
    observed = mapped(AXIS)
    result = snap(observed)

    assert np.array_equal(result.as_grid(result.snap.snapped), observed)
    assert result.snap.displacement_p90_m == pytest.approx(0.0)


def test_the_network_drains_to_the_border_of_the_raster() -> None:
    result = snap(mapped(AXIS + 1))
    rows, cols = np.divmod(result.outlets, N_COLS)
    border = (rows == 0) | (rows == N_ROWS - 1) | (cols == 0) | (cols == N_COLS - 1)

    assert result.outlets.size > 0
    assert border.all()
    assert result.snap.connected_share == pytest.approx(1.0)


def test_the_radius_follows_the_rule_of_the_criterion() -> None:
    result = snap(mapped(AXIS + 1), radius="2 cells")

    assert result.snap.h_obs_m == pytest.approx(CELL)
    assert result.snap.radius_m == pytest.approx(2.0 * CELL)


def test_a_radius_short_of_the_axis_rejects_the_map() -> None:
    result = snap(mapped(AXIS + 3), radius="1 cell")

    assert result.snap.rejected_share > 0.5


def test_the_grid_snap_equals_the_mesh_snap_it_is_built_from() -> None:
    # The same quad mesh, descended by the same builders: the raster snap is
    # the mesh snap, not a second algorithm.
    from hydromodpy.core.depression_filling import fill_depressions_on_graph
    from hydromodpy.core.field_routing import domain_edge_cells
    from hydromodpy.core.stream_snap import snap_observed_network

    result = snap(mapped(AXIS + 1))
    vertices, faces = grid_quad_mesh(
        (N_ROWS, N_COLS), x_origin=0.0, y_origin=TOP, dx=CELL, dy=-CELL
    )
    n_cells = N_ROWS * N_COLS
    adjacency = shared_node_adjacency(faces, n_cells=n_cells)
    active = np.ones(n_cells, dtype=bool)
    surface = fill_depressions_on_graph(
        valley().reshape(-1), adjacency, domain_edge_cells(faces, active)
    ).surface
    metric = build_downslope_metric(surface, faces, vertices=vertices, adjacency=adjacency)
    direct = snap_observed_network(
        metric=metric,
        observed=mapped(AXIS + 1).reshape(-1),
        outlet=np.flatnonzero(metric.graph.downstream < 0),
        catchment=active,
        cell_area_m2=np.full(n_cells, CELL * CELL),
        adjacency=adjacency,
        h_obs_m=CELL,
        settings=SnapStreamsConfig(mode="apply"),
    )

    assert np.array_equal(direct.snapped, result.snap.snapped)


def test_off_computes_nothing() -> None:
    with pytest.raises(ValueError, match="off"):
        snap(mapped(AXIS), mode="off")


def test_a_map_outside_the_raster_is_refused() -> None:
    with pytest.raises(ValueError, match="covers no valid cell"):
        snap(np.zeros((N_ROWS, N_COLS), dtype=bool))

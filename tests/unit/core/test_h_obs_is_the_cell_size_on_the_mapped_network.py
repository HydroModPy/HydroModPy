"""``h_obs``: the length ``roptim``, the Eq. 4 length and the interval width read.

It is the median distance between the centres of neighbouring cells over the
mapped cells of the catchment. On a regular grid it is the cell size, so the
numbers of the paper do not move; on a mesh refined along the streams it is the
fine cell the distances start from, not the median cell of the catchment.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.stream_geometry import build_network_geometry, observed_cell_size_m
from tests._helpers.ugrid_meshes import quad_mesh


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

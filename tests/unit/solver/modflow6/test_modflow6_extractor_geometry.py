"""WP15 - the flow extractor preserves a non-zero grid origin in mesh geometry."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter


def test_flow_extractor_mesh_geometry_preserves_nonzero_origin() -> None:
    # 2x2 grid (4 cells), vertices translated by xorigin=1000, yorigin=2000, dx=dy=10.
    x_edges = np.array([1000.0, 1010.0, 1020.0])
    y_edges = np.array([2000.0, 2010.0, 2020.0])
    xx, yy = np.meshgrid(x_edges, y_edges)
    rings = [[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]]
    closed = [[*ring, ring[0]] for ring in rings]
    grid = SimpleNamespace(
        verts=np.column_stack([xx.ravel(), yy.ravel()]),
        iavert=np.concatenate([[0], np.cumsum([len(r) for r in closed])]),
        javert=np.concatenate(closed),
    )

    geometry = Modflow6OutputAdapter._mesh_geometry_from_grid(grid, n_cells=4)
    assert geometry is not None
    vertices, connectivity = geometry

    assert vertices[:, 0].min() == 1000.0
    assert vertices[:, 0].max() == 1020.0
    assert vertices[:, 1].min() == 2000.0
    assert vertices[:, 1].max() == 2020.0
    assert np.all(vertices[:, 2] == 0.0)
    np.testing.assert_array_equal(connectivity, np.array(rings, dtype="int32"))


def test_a_grid_file_without_vertices_gives_no_geometry() -> None:
    structured = SimpleNamespace(verts=None, iavert=None, javert=None)

    assert Modflow6OutputAdapter._mesh_geometry_from_grid(structured, n_cells=4) is None

"""WP15 - the flow extractor preserves a non-zero grid origin in mesh geometry."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter


def test_flow_extractor_mesh_geometry_preserves_nonzero_origin() -> None:
    # 2x2 grid (4 cells), vertices translated by xorigin=1000, yorigin=2000, dx=dy=10.
    # No verts/iverts -> the modelgrid (structured) branch is exercised.
    x_edges = np.array([1000.0, 1010.0, 1020.0])
    y_edges = np.array([2000.0, 2010.0, 2020.0])
    xx, yy = np.meshgrid(x_edges, y_edges)
    grid = SimpleNamespace(
        verts=None,
        iverts=None,
        modelgrid=SimpleNamespace(xvertices=xx, yvertices=yy),
    )

    geometry = Modflow6OutputAdapter._mesh_geometry_from_grid(grid, n_cells=4)
    assert geometry is not None
    vertices, connectivity = geometry

    assert vertices[:, 0].min() == 1000.0
    assert vertices[:, 0].max() == 1020.0
    assert vertices[:, 1].min() == 2000.0
    assert vertices[:, 1].max() == 2020.0
    assert np.all(vertices[:, 2] == 0.0)
    # Structured quad connectivity, one row per cell.
    assert connectivity.shape == (4, 4)

"""Unit tests for planar field-mesh adaptation from structured solver grids."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.spatial.field.meshes import StructuredFieldMesh
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_mesh_adapter import (
    build_field_mesh_from_sgrid,
)


def test_build_field_mesh_from_sgrid_returns_generic_structured_mesh():
    sgrid = SimpleNamespace(
        nrow=2,
        ncol=3,
        xvertices=np.array([[0.0, 1.0, 3.0, 6.0], [0.0, 1.0, 3.0, 6.0], [0.0, 1.0, 3.0, 6.0]]),
        yvertices=np.array([[10.0, 10.0, 10.0, 10.0], [7.0, 7.0, 7.0, 7.0], [2.0, 2.0, 2.0, 2.0]]),
    )

    mesh = build_field_mesh_from_sgrid(sgrid)

    assert isinstance(mesh, StructuredFieldMesh)
    assert mesh.shape == (3, 4)
    assert mesh.n_cells == 6
    assert mesh.target_n_cells == 6
    assert np.allclose(mesh.x_plot, sgrid.xvertices)
    assert np.allclose(mesh.y_plot, sgrid.yvertices)

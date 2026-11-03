"""Planar cell meshes for the solver and workflow unit tests.

``cell_mesh_of`` wraps a hand-built planar ``HydroMesh`` into the
``PlanarCellMesh`` the solvers read. Centers are the vertex means. Not public
API.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

TEST_CRS_WKT = 'PROJCS["test",GEOGCS["test"]]'
"""Any non-empty text: the solvers never parse the CRS of a cell mesh."""


def cell_mesh_of(mesh: HydroMesh) -> PlanarCellMesh:
    """Wrap a planar mesh with its vertex-mean centers and no family."""
    x_centers, y_centers = mesh.cell_centroids()
    return build_planar_cell_mesh(
        mesh,
        np.column_stack([x_centers, y_centers]),
        center_kind="vertex_mean",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
    )

"""Planar cell meshes for the solver and workflow unit tests.

``cell_mesh_of`` wraps a hand-built planar mesh, a ``HydroMesh`` or a Gmsh
planar mesh, into the ``PlanarCellMesh`` the solvers read. Centres are the
vertex means. Not public API.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.field.meshes.field_mesh_adapter import from_gmsh_planar
from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

TEST_CRS_WKT = 'PROJCS["test",GEOGCS["test"]]'
"""Any non-empty text: the solvers never parse the CRS of a cell mesh."""


def cell_mesh_of(mesh: object) -> PlanarCellMesh:
    """Wrap a planar mesh with its vertex-mean centres and no family."""
    hydro = mesh if isinstance(mesh, HydroMesh) else from_gmsh_planar(mesh)
    x_centers, y_centers = hydro.cell_centroids()
    return build_planar_cell_mesh(
        hydro,
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

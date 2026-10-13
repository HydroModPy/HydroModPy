"""Solver mesh over a hand-built planar mesh, for the scripts that drive a MODFLOW model by hand."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import MeshIdentity, build_planar_cell_mesh

_LOCAL_CRS_WKT = (
    'LOCAL_CS["validation case",LOCAL_DATUM["local origin",0],UNIT["metre",1],'
    'AXIS["X",EAST],AXIS["Y",NORTH]]'
)


def solver_mesh_of(
    planar: HydroMesh, *, top: np.ndarray, botm: np.ndarray, inactive_mask: np.ndarray
) -> SolverMesh:
    """Return the solver mesh of *planar*, in a local frame in metres.

    The cell centres are the generators of ``cell_data["disv_cell_center"]`` when the
    mesh carries them (a Voronoi mesh), the vertex means otherwise.
    """
    x_centers, y_centers = planar.cell_centroids()
    cell_mesh = build_planar_cell_mesh(
        planar,
        np.column_stack([x_centers, y_centers]),
        center_kind="generator" if "disv_cell_center" in planar.cell_data else "vertex_mean",
        crs_wkt=_LOCAL_CRS_WKT,
        identity=MeshIdentity("validation_case", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
        structured_shape=planar.structured_shape,
    )
    return SolverMesh(cell_mesh=cell_mesh, top=top, botm=botm, inactive_mask=inactive_mask)

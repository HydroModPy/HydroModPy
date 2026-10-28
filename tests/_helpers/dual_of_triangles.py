"""The Voronoi dual of a triangle mesh, built by the engine from the triangles it reads.

Not public API.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.request import InputTriangulation, MeshRequest
from tests._helpers.mesh_cases import mesh_request

RIVER_GROUP = "river::trace"


def dual_of_the_triangles(triangles: PlanarCellMesh, request: MeshRequest) -> PlanarCellMesh:
    """Read the triangles of *request* back, with their river edges, and take their dual."""
    table = triangles.face_families
    rows = triangles.face_rows("rivers")
    river_edges = np.column_stack([table.node_a[rows], table.node_b[rows]])
    triangulation = InputTriangulation(
        triangles.mesh.vertices,
        np.asarray(triangles.mesh.flat_connectivity),
        {RIVER_GROUP: river_edges},
    )
    read = mesh_request(
        request.grid,
        domain=request.domain,
        nominal_size_m=request.nominal_size_m,
        input_triangulation=triangulation,
    )
    return VoronoiMeshEngine().build(read)

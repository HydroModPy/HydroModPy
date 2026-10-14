"""Cell meshes of the committed validation mesh bundles.

``bundle_triangles`` reads the triangles of a bundle as a ``PlanarCellMesh``;
``bundle_dual`` is the Voronoi dual of those triangles, built by the engine. The
committed bundles flag no river edge, so neither mesh has a ``rivers`` family.
Not public API.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.spatial.mesh.engines.voronoi.engine import VoronoiMeshEngine
from hydromodpy.spatial.mesh.gmsh_grid.bundle_cell_mesh import cell_mesh_from_bundle
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh
from hydromodpy.spatial.mesh.request import InputTriangulation, MeshRequest, RasterGridSpec
from tests._helpers.cell_meshes import TEST_CRS_WKT

BUNDLES = Path(__file__).resolve().parents[2] / "validation_cases" / "shared" / "mesh_bundles"
BUNDLE_CASES = (
    "boussinesq_circular_island_piecewise_k_irregular_tri_radial_48",
    "stream_depletion_glover_balmer_tri_refined_well",
    "linearized_unconfined_tide_irregular_tri_100x10",
    "hantush_recharge_mound_tri_conforming",
)


def bundle_triangles(case: str) -> PlanarCellMesh:
    """Return the triangles of one bundle as a cell mesh."""
    return cell_mesh_from_bundle(load_catchment_mesh_bundle(BUNDLES / case), crs_wkt=TEST_CRS_WKT)


def bundle_dual(case: str) -> PlanarCellMesh:
    """Return the Voronoi dual of the triangles of one bundle as a cell mesh."""
    triangles = bundle_triangles(case)
    domain = domain_polygon_from_mesh(triangles.mesh)
    xmin, ymin, xmax, ymax = domain.bounds
    request = MeshRequest(
        domain=domain,
        crs_wkt=TEST_CRS_WKT,
        grid=RasterGridSpec(
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            dx=xmax - xmin,
            dy=ymax - ymin,
            nrow=1,
            ncol=1,
            crs_wkt=TEST_CRS_WKT,
        ),
        nominal_size_m=float(np.sqrt(np.median(triangles.geometry.areas))),
        input_triangulation=InputTriangulation(
            triangles.mesh.vertices, np.asarray(triangles.mesh.flat_connectivity), {}
        ),
    )
    return VoronoiMeshEngine().build(request)

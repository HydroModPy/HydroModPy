"""Cell meshes of the committed validation mesh bundles, with the support they were read with.

``bundle_triangles`` and ``bundle_dual`` return a ``PlanarCellMesh`` through the adapters
of the legacy producers, together with the ``GmshSupportMetadata`` the solvers read
before the cell mesh: the oracle the family and location helpers are compared to.
Not public API.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.mesh.adapters.cell_mesh import (
    cell_mesh_from_triangulation,
    cell_mesh_from_voronoi_dual,
)
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import (
    GmshSupportMetadata,
    build_gmsh_support_metadata,
    support_on_planar_mesh,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh, voronoi_dual_of_mesh
from tests._helpers.cell_meshes import TEST_CRS_WKT

BUNDLES = Path(__file__).resolve().parents[2] / "validation_cases" / "shared" / "mesh_bundles"
BUNDLE_CASES = (
    "boussinesq_circular_island_piecewise_k_irregular_tri_radial_48",
    "stream_depletion_glover_balmer_tri_refined_well",
    "linearized_unconfined_tide_irregular_tri_100x10",
    "hantush_recharge_mound_tri_conforming",
)


def bundle_triangles(case: str) -> tuple[PlanarCellMesh, GmshSupportMetadata]:
    """Return the triangles of one bundle as a cell mesh, and the support read from its files."""
    bundle = BUNDLES / case
    support = build_gmsh_support_metadata(load_catchment_mesh_bundle(bundle))
    triangles = load_planar_mesh(bundle / "mesh_2d.msh").to_hydro_mesh()
    return cell_mesh_from_triangulation(triangles, support, crs_wkt=TEST_CRS_WKT), support


def bundle_dual(case: str) -> tuple[PlanarCellMesh, GmshSupportMetadata]:
    """Return the Voronoi dual of one bundle as a cell mesh, and the support rebuilt on it."""
    bundle = BUNDLES / case
    support = build_gmsh_support_metadata(load_catchment_mesh_bundle(bundle))
    triangles = load_planar_mesh(bundle / "mesh_2d.msh").to_hydro_mesh()
    dual = voronoi_dual_of_mesh(triangles, domain_polygon_from_mesh(triangles))
    on_dual = support_on_planar_mesh(support, dual)
    return cell_mesh_from_voronoi_dual(dual, on_dual, crs_wkt=TEST_CRS_WKT), on_dual

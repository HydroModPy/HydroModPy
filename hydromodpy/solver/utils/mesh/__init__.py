"""Mesh helper package shared by solver-side workflows."""

from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_mesh_adapter import (
    build_field_mesh_from_sgrid,
    extract_structured_vertices,
)
from hydromodpy.solver.utils.mesh.gmsh_grid import (
    ExtrudedFieldParamDiscretizationResult,
    ExtrudedPrismMesh3D,
    ExtrudedPrismMeshData,
    ExtrudedPrismMeshWithValues,
    GmshMeshData,
    GmshPlanarMesh2D,
    attach_extruded_values,
    discretize_fieldparam_on_extruded_mesh,
    read_extruded_prism_mesh,
    read_gmsh_2d_mesh,
    write_extruded_prism_mesh,
    write_gmsh_2d_mesh,
)

__all__ = [
    "build_field_mesh_from_sgrid",
    "extract_structured_vertices",
    "ExtrudedFieldParamDiscretizationResult",
    "ExtrudedPrismMesh3D",
    "ExtrudedPrismMeshData",
    "ExtrudedPrismMeshWithValues",
    "GmshMeshData",
    "GmshPlanarMesh2D",
    "attach_extruded_values",
    "discretize_fieldparam_on_extruded_mesh",
    "read_extruded_prism_mesh",
    "read_gmsh_2d_mesh",
    "write_extruded_prism_mesh",
    "write_gmsh_2d_mesh",
]

"""Compatibility facade for low-level Gmsh helpers used by zone meshing."""

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._gmsh_export import (
    build_runtime_planar_mesh_from_gmsh,
    write_repository_compatible_mesh,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._gmsh_fields import (
    apply_family_refinement_fields,
    apply_interface_refinement_field,
    create_regional_structured_size_field,
    set_background_mesh_from_fields,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._gmsh_occ import (
    add_polyline_segments,
    add_ring_loop,
    apply_mesh_options,
    build_curve_group_name,
    configure_gmsh_terminal_output,
    iter_river_lines_from_trace,
)

__all__ = [
    "add_polyline_segments",
    "add_ring_loop",
    "create_regional_structured_size_field",
    "build_runtime_planar_mesh_from_gmsh",
    "apply_family_refinement_fields",
    "apply_interface_refinement_field",
    "apply_mesh_options",
    "build_curve_group_name",
    "configure_gmsh_terminal_output",
    "iter_river_lines_from_trace",
    "set_background_mesh_from_fields",
    "write_repository_compatible_mesh",
]

"""Mesh helper package shared by solver-side workflows, loaded lazily."""

from __future__ import annotations

from importlib import import_module

_CARTESIAN_EXPORTS = {
    "build_field_mesh_from_sgrid",
    "extract_structured_vertices",
}
_GMSH_EXPORTS = {
    "ExtrudedFieldParamDiscretizationResult",
    "ExtrudedPrismMesh3D",
    "ExtrudedPrismMeshData",
    "ExtrudedPrismMeshWithValues",
    "GmshMeshData",
    "GmshPlanarMesh2D",
    "add_bounds_axes",
    "add_clip_plane",
    "add_layer_slice",
    "add_threshold",
    "add_vertical_exaggeration",
    "attach_extruded_values",
    "build_layer_maps_figure",
    "build_pyvista_grid",
    "build_pyvista_grid_with_values",
    "build_vertical_profiles_figure",
    "discretize_fieldparam_on_extruded_mesh",
    "extract_prism_pick_info",
    "extract_source_column_grid",
    "load_extruded_mesh",
    "load_extruded_mesh_values",
    "load_planar_mesh",
    "read_extruded_prism_mesh",
    "read_gmsh_2d_mesh",
    "save_extruded_mesh",
    "save_extruded_mesh_values",
    "save_extruded_values_npy",
    "save_extruded_values_summary",
    "save_planar_mesh",
    "show_interactive_mesh_3d",
    "show_interactive_values_3d",
    "write_extruded_prism_mesh",
    "write_gmsh_2d_mesh",
}

__all__ = [
    "build_field_mesh_from_sgrid",
    "extract_structured_vertices",
    "ExtrudedFieldParamDiscretizationResult",
    "ExtrudedPrismMesh3D",
    "ExtrudedPrismMeshData",
    "ExtrudedPrismMeshWithValues",
    "GmshMeshData",
    "GmshPlanarMesh2D",
    "add_bounds_axes",
    "add_clip_plane",
    "add_layer_slice",
    "add_threshold",
    "add_vertical_exaggeration",
    "attach_extruded_values",
    "build_layer_maps_figure",
    "build_pyvista_grid",
    "build_pyvista_grid_with_values",
    "build_vertical_profiles_figure",
    "discretize_fieldparam_on_extruded_mesh",
    "extract_prism_pick_info",
    "extract_source_column_grid",
    "load_extruded_mesh",
    "load_extruded_mesh_values",
    "load_planar_mesh",
    "read_extruded_prism_mesh",
    "read_gmsh_2d_mesh",
    "save_extruded_mesh",
    "save_extruded_mesh_values",
    "save_extruded_values_npy",
    "save_extruded_values_summary",
    "save_planar_mesh",
    "show_interactive_mesh_3d",
    "show_interactive_values_3d",
    "write_extruded_prism_mesh",
    "write_gmsh_2d_mesh",
]


def __getattr__(name: str):
    if name in _CARTESIAN_EXPORTS:
        module = import_module(
            "hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_mesh_adapter"
        )
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _GMSH_EXPORTS:
        module = import_module("hydromodpy.solver.utils.mesh.gmsh_grid")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

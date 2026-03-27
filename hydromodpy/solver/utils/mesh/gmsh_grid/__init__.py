"""Public entry points for the reusable ``gmsh_grid`` mesh workflow.

The package exposes many classes and helper functions, but most users only need
the public names re-exported here. Lazy imports keep import time low and avoid
pulling optional dependencies such as ``gmsh``, ``meshio`` or ``pyvista``
before they are actually needed.
"""

from __future__ import annotations

from importlib import import_module

_EXPORT_TO_MODULE = {
    "BUNDLE_SCHEMA_VERSION": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "CatchmentMeshBundle": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "CatchmentMeshBundleCell": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "CatchmentMeshBundleEdge": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "CatchmentMeshBundleGeologyFraction": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "CatchmentMeshBundleNode": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "export_catchment_mesh_bundle": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "load_catchment_mesh_bundle": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "resolve_default_catchment_mesh_bundle_dir": "hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle",
    "ExtrudedFieldParamDiscretizationResult": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_fieldparam_discretization",
    "discretize_fieldparam_on_extruded_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_fieldparam_discretization",
    "ExtrudedPrismMeshWithValues": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_values",
    "attach_extruded_values": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_values",
    "build_layer_maps_figure": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "build_source_cell_marker_specs": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "build_vertical_profiles_figure": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "build_visualization_summary": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "plot_planar_cell_values": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "plot_source_cell_markers": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "select_default_layer_indices": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "select_default_source_cell_indices": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization",
    "ExtrudedPrismMesh3D": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh",
    "ExtrudedPrismMeshData": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh",
    "PrismCell3D": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh",
    "read_extruded_prism_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh",
    "write_extruded_prism_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh",
    "load_extruded_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "load_extruded_mesh_values": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "load_planar_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "save_extruded_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "save_extruded_mesh_values": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "save_extruded_values_npy": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "save_extruded_values_summary": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "save_planar_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api",
    "GmshPlanarMesh2D": "hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh",
    "GmshCellBlock": "hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader",
    "GmshMeshData": "hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader",
    "mesh_data_to_meshio": "hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader",
    "read_gmsh_2d_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader",
    "write_gmsh_2d_mesh": "hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader",
    "add_bounds_axes": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "add_clip_plane": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "add_layer_slice": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "add_threshold": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "add_vertical_exaggeration": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "build_pyvista_grid": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "build_pyvista_grid_with_values": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "extract_prism_pick_info": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "extract_source_column_grid": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "show_interactive_mesh_3d": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "show_interactive_values_3d": "hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer",
    "ZoneConformalPhysicalGroup": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "ZoneConformalMeshResult": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "ZoneConformalPartition": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "ZoneLinearConstraint": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "ZoneMeshingDomainConfig": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "ZoneMeshingDomainPayload": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "ZoneMeshingSettings": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "ZonePartitionFace": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "build_zone_conformal_partition_from_dataframe": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "generate_zone_conformal_mesh_from_dataframe": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "generate_zone_conformal_mesh_from_geology_config": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "load_zone_meshing_domain_payload": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "parse_zone_meshing_domain_config": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
    "parse_zone_meshing_settings": "hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing",
}

__all__ = list(_EXPORT_TO_MODULE)


def __getattr__(name: str):
    """Resolve one exported symbol lazily from its implementation module."""
    module_name = _EXPORT_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value

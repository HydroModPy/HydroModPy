"""Public entry points for the Gmsh mesh workflow.

Import from this package when you want the high-level API instead of the
individual implementation modules. It gathers the planar mesh wrapper, the 3D
extrusion helpers, and the utilities used to attach values and export results.
"""

from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_fieldparam_discretization import (
    ExtrudedFieldParamDiscretizationResult,
    discretize_fieldparam_on_extruded_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_values import (
    ExtrudedPrismMeshWithValues,
    attach_extruded_values,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_visualization import (
    build_layer_maps_figure,
    build_source_cell_marker_specs,
    build_vertical_profiles_figure,
    build_visualization_summary,
    plot_planar_cell_values,
    plot_source_cell_markers,
    select_default_layer_indices,
    select_default_source_cell_indices,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh import (
    ExtrudedPrismMesh3D,
    ExtrudedPrismMeshData,
    PrismCell3D,
    read_extruded_prism_mesh,
    write_extruded_prism_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.exchange_api import (
    load_extruded_mesh,
    load_extruded_mesh_values,
    load_planar_mesh,
    save_extruded_mesh,
    save_extruded_mesh_values,
    save_extruded_values_npy,
    save_extruded_values_summary,
    save_planar_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader import (
    GmshCellBlock,
    GmshMeshData,
    mesh_data_to_meshio,
    read_gmsh_2d_mesh,
    write_gmsh_2d_mesh,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.interactive_3d_viewer import (
    add_bounds_axes,
    add_clip_plane,
    add_layer_slice,
    add_threshold,
    add_vertical_exaggeration,
    build_pyvista_grid,
    build_pyvista_grid_with_values,
    extract_prism_pick_info,
    extract_source_column_grid,
    show_interactive_mesh_3d,
    show_interactive_values_3d,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing import (
    ZoneConformalPhysicalGroup,
    ZoneConformalMeshResult,
    ZoneConformalPartition,
    ZonePartitionFace,
    build_zone_conformal_partition_from_dataframe,
    generate_zone_conformal_mesh_from_dataframe,
    generate_zone_conformal_mesh_from_geology_config,
    load_zone_meshing_domain_geometry,
    validate_zone_meshing_config_data,
    validate_zone_meshing_domain_config_data,
)

__all__ = [
    "ExtrudedFieldParamDiscretizationResult",
    "ExtrudedPrismMesh3D",
    "ExtrudedPrismMeshData",
    "ExtrudedPrismMeshWithValues",
    "GmshCellBlock",
    "GmshMeshData",
    "GmshPlanarMesh2D",
    "PrismCell3D",
    "add_bounds_axes",
    "add_clip_plane",
    "add_layer_slice",
    "add_threshold",
    "add_vertical_exaggeration",
    "attach_extruded_values",
    "ZoneConformalPhysicalGroup",
    "ZoneConformalMeshResult",
    "ZoneConformalPartition",
    "ZonePartitionFace",
    "build_layer_maps_figure",
    "build_pyvista_grid",
    "build_pyvista_grid_with_values",
    "build_source_cell_marker_specs",
    "build_vertical_profiles_figure",
    "build_zone_conformal_partition_from_dataframe",
    "build_visualization_summary",
    "discretize_fieldparam_on_extruded_mesh",
    "extract_prism_pick_info",
    "extract_source_column_grid",
    "generate_zone_conformal_mesh_from_dataframe",
    "generate_zone_conformal_mesh_from_geology_config",
    "load_zone_meshing_domain_geometry",
    "load_extruded_mesh",
    "load_extruded_mesh_values",
    "load_planar_mesh",
    "mesh_data_to_meshio",
    "plot_planar_cell_values",
    "plot_source_cell_markers",
    "read_extruded_prism_mesh",
    "read_gmsh_2d_mesh",
    "save_extruded_mesh",
    "save_extruded_mesh_values",
    "save_extruded_values_npy",
    "save_extruded_values_summary",
    "save_planar_mesh",
    "select_default_layer_indices",
    "select_default_source_cell_indices",
    "show_interactive_mesh_3d",
    "show_interactive_values_3d",
    "validate_zone_meshing_config_data",
    "validate_zone_meshing_domain_config_data",
    "write_extruded_prism_mesh",
    "write_gmsh_2d_mesh",
]

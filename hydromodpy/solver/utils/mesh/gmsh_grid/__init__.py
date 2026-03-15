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

__all__ = [
    "ExtrudedFieldParamDiscretizationResult",
    "ExtrudedPrismMesh3D",
    "ExtrudedPrismMeshData",
    "ExtrudedPrismMeshWithValues",
    "GmshCellBlock",
    "GmshMeshData",
    "GmshPlanarMesh2D",
    "PrismCell3D",
    "attach_extruded_values",
    "build_layer_maps_figure",
    "build_source_cell_marker_specs",
    "build_vertical_profiles_figure",
    "build_visualization_summary",
    "discretize_fieldparam_on_extruded_mesh",
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
    "write_extruded_prism_mesh",
    "write_gmsh_2d_mesh",
]

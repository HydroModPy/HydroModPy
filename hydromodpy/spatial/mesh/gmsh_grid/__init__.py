"""Public entry points for the ``gmsh_grid`` mesh readers.

The package reads a Gmsh ``.msh`` file into a planar mesh, converts it to and from the
``HydroMesh`` and its VTU file, and loads a frozen catchment mesh bundle. Lazy imports keep
import time low and avoid pulling optional dependencies such as ``gmsh`` or ``meshio`` before
they are needed.
"""

from __future__ import annotations

from importlib import import_module

_EXPORT_TO_MODULE = {
    "CatchmentMeshBundle": "hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader",
    "CatchmentMeshBundleCell": "hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader",
    "CatchmentMeshBundleEdge": "hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader",
    "CatchmentMeshBundleGeologyFraction": "hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader",
    "CatchmentMeshBundleNode": "hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader",
    "load_catchment_mesh_bundle": "hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader",
    "load_hydro_mesh_vtu": "hydromodpy.spatial.mesh.gmsh_grid.exchange_api",
    "load_planar_as_hydro_mesh": "hydromodpy.spatial.mesh.gmsh_grid.exchange_api",
    "load_planar_mesh": "hydromodpy.spatial.mesh.gmsh_grid.exchange_api",
    "save_hydro_mesh_vtu": "hydromodpy.spatial.mesh.gmsh_grid.exchange_api",
    "save_planar_mesh": "hydromodpy.spatial.mesh.gmsh_grid.exchange_api",
    "GmshPlanarMesh2D": "hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh",
    "GmshCellBlock": "hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader",
    "GmshMeshData": "hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader",
    "mesh_data_to_meshio": "hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader",
    "read_gmsh_2d_mesh": "hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader",
    "write_gmsh_2d_mesh": "hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader",
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

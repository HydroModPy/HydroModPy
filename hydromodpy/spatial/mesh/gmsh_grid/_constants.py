"""Shared metadata keys for the ``gmsh_grid`` package.

These keys are written to ``meshio`` point/cell data when HydroModPy exports an
extruded mesh. They are then reused later by readers, value attachers and
interactive viewers to reconstruct the layered structure of the mesh.
"""

from __future__ import annotations

# meshio point_data / cell_data keys written by ``extruded_prism_mesh`` and
# read later by the value and viewer helpers.
POINT_LAYER_KEY = "hydromodpy_point_layer_index"
POINT_BASE_KEY = "hydromodpy_point_base_index"
CELL_LAYER_KEY = "hydromodpy_cell_layer_index"
CELL_SOURCE_KEY = "hydromodpy_cell_source_index"

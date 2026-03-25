"""Adapters between ``HydroMesh`` and the field/mesh layer.

These functions bridge the existing ``BaseFieldMesh`` hierarchy
(``StructuredFieldMesh``, triangular field meshes, ``GmshPlanarMesh2D``,
``ExtrudedPrismMesh3D``) and the unified ``HydroMesh`` pivot.

This module is deliberately pragmatic: it recognizes the small set of mesh
objects that HydroModPy itself emits today and converts them into a single
container with minimal additional policy.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh


def from_field_mesh(field_mesh) -> HydroMesh:
    """Convert any ``BaseFieldMesh`` subclass into a ``HydroMesh``.

    Works for:
    - ``StructuredFieldMesh`` (quadrilateral, 2D grid layout)
    - ``TriangularStructuredFieldMesh`` / ``TriangularUnstructuredFieldMesh``
    - ``GmshPlanarMesh2D``

    Notes
    -----
    The function currently uses lightweight attribute detection rather than a
    formal protocol.  This is convenient, but it is also one of the places
    where a future refactor could make the mesh layer stricter.
    """
    # GmshPlanarMesh2D has explicit points_xy and connectivity
    if hasattr(field_mesh, "points_xy") and hasattr(field_mesh, "connectivity"):
        return from_gmsh_planar(field_mesh)

    # Structured or triangular mesh: reconstruct from cells
    x = np.asarray(field_mesh.x_plot, dtype=float)
    y = np.asarray(field_mesh.y_plot, dtype=float)
    vertices = np.column_stack((x.reshape(-1), y.reshape(-1)))

    cells = tuple(field_mesh.cells)
    if not cells:
        raise ValueError("field_mesh has no cells")

    first_kind = cells[0].kind
    ct = CellType.from_string(first_kind)
    connectivity = np.array(
        [cell.node_indices for cell in cells], dtype=int
    )

    structured_shape = None
    if x.ndim == 2:
        ny, nx = x.shape
        structured_shape = (ny - 1, nx - 1)

    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(cell_type=ct, connectivity=connectivity),),
        structured_shape=structured_shape,
    )


def from_gmsh_planar(planar_mesh) -> HydroMesh:
    """Convert a planar Gmsh-like mesh object into a ``HydroMesh``."""
    points_xy = np.asarray(planar_mesh.points_xy, dtype=float)
    connectivity = np.asarray(planar_mesh.connectivity, dtype=int)
    ct = CellType.from_string(planar_mesh.cell_type)

    return HydroMesh(
        vertices=points_xy,
        cell_blocks=(CellBlock(cell_type=ct, connectivity=connectivity),),
    )


def from_extruded_prism(extruded_mesh) -> HydroMesh:
    """Convert an ``ExtrudedPrismMesh3D`` into a 3D ``HydroMesh``.

    Layer and source-cell metadata are preserved as ``cell_data`` /
    ``point_data`` so that downstream solvers and diagnostics can keep the
    vertical provenance of each prism.
    """
    points_xyz = np.asarray(extruded_mesh.points_xyz, dtype=float)
    connectivity = np.asarray(extruded_mesh.prism_connectivity, dtype=int)

    cell_type_2d = str(extruded_mesh.cell_type_2d).strip().lower()
    if cell_type_2d == "triangle":
        ct = CellType.WEDGE
    else:
        ct = CellType.HEXAHEDRON

    cell_data: dict[str, np.ndarray] = {
        "layer_index": np.asarray(extruded_mesh.layer_indices, dtype=int),
        "source_cell_index": np.asarray(extruded_mesh.source_cell_indices, dtype=int),
    }
    point_data: dict[str, np.ndarray] = {
        "layer_index": np.asarray(extruded_mesh.point_layer_indices, dtype=int),
        "base_index": np.asarray(extruded_mesh.point_base_indices, dtype=int),
    }

    return HydroMesh(
        vertices=points_xyz,
        cell_blocks=(CellBlock(cell_type=ct, connectivity=connectivity),),
        cell_data=cell_data,
        point_data=point_data,
    )

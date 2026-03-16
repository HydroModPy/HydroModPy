"""Expose the simplest public I/O API for the solver-independent Gmsh workflow.

This module is the entry point to use when a caller only needs to load or save
2D meshes, 3D extruded meshes, or 3D values attached to prisms. It deliberately
hides the lower-level implementation modules so colleagues can work with a
small and stable surface.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_mesh_values import (
    ExtrudedPrismMeshWithValues,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.extruded_prism_mesh import (
    ExtrudedPrismMesh3D,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D


def load_planar_mesh(
    path: str | Path, *, cell_type: str | None = None
) -> GmshPlanarMesh2D:
    """Read one 2D planar mesh from disk."""
    return GmshPlanarMesh2D.from_file(path, cell_type=cell_type)


def save_planar_mesh(
    mesh: GmshPlanarMesh2D,
    path: str | Path,
    *,
    file_format: str | None = None,
) -> Path:
    """Write one 2D planar mesh to disk."""
    if not isinstance(mesh, GmshPlanarMesh2D):
        raise TypeError("mesh must be a GmshPlanarMesh2D instance")
    return mesh.to_file(path, file_format=file_format)


def load_extruded_mesh(path: str | Path) -> ExtrudedPrismMesh3D:
    """Read one extruded 3D prism mesh from disk."""
    return ExtrudedPrismMesh3D.from_file(path)


def save_extruded_mesh(
    mesh: ExtrudedPrismMesh3D,
    path: str | Path,
    *,
    file_format: str | None = None,
) -> Path:
    """Write one extruded 3D prism mesh to disk."""
    if not isinstance(mesh, ExtrudedPrismMesh3D):
        raise TypeError("mesh must be an ExtrudedPrismMesh3D instance")
    return mesh.to_file(path, file_format=file_format)


def load_extruded_mesh_values(
    path: str | Path,
    *,
    value_name: str = "field_param_value",
    depth_name: str = "prism_center_depth",
    label: str | None = None,
) -> ExtrudedPrismMeshWithValues:
    """Read one 3D prism mesh together with prism values."""
    return ExtrudedPrismMeshWithValues.from_file(
        path,
        value_name=value_name,
        depth_name=depth_name,
        label=label,
    )


def save_extruded_mesh_values(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    path: str | Path,
    *,
    value_name: str = "field_param_value",
    depth_name: str = "prism_center_depth",
    file_format: str | None = None,
) -> Path:
    """Write one 3D prism mesh carrying prism values."""
    if not isinstance(mesh_with_values, ExtrudedPrismMeshWithValues):
        raise TypeError(
            "mesh_with_values must be an ExtrudedPrismMeshWithValues instance"
        )
    return mesh_with_values.to_file(
        path,
        value_name=value_name,
        depth_name=depth_name,
        file_format=file_format,
    )


def save_extruded_values_npy(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    path: str | Path,
) -> Path:
    """Write the `(n_layers, n_cells_2d)` value array to a `.npy` file."""
    if not isinstance(mesh_with_values, ExtrudedPrismMeshWithValues):
        raise TypeError(
            "mesh_with_values must be an ExtrudedPrismMeshWithValues instance"
        )
    return mesh_with_values.to_npy(path)


def save_extruded_values_summary(
    mesh_with_values: ExtrudedPrismMeshWithValues,
    path: str | Path,
) -> Path:
    """Write a compact JSON summary of attached 3D prism values."""
    if not isinstance(mesh_with_values, ExtrudedPrismMeshWithValues):
        raise TypeError(
            "mesh_with_values must be an ExtrudedPrismMeshWithValues instance"
        )
    return mesh_with_values.write_summary_json(path)

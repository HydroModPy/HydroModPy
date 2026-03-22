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
    """Read one 2D planar mesh into the package-level mesh object."""
    return GmshPlanarMesh2D.from_file(path, cell_type=cell_type)


def save_planar_mesh(
    mesh: GmshPlanarMesh2D,
    path: str | Path,
    *,
    file_format: str | None = None,
) -> Path:
    """Write one planar mesh through the stable package I/O surface."""
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
    """Read one 3D prism mesh together with the scalar values attached to prisms."""
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
    """Write one valued 3D prism mesh to disk."""
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
    """Write the canonical ``(n_layers, n_cells_2d)`` value array to ``.npy``."""
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


# ---------------------------------------------------------------------------
# Unified HydroMesh bridge
# ---------------------------------------------------------------------------


def load_planar_as_hydro_mesh(
    path: str | Path, *, cell_type: str | None = None
):
    """Read one planar mesh and convert it directly to the generic ``HydroMesh``."""
    return load_planar_mesh(path, cell_type=cell_type).to_hydro_mesh()


def load_extruded_as_hydro_mesh(path: str | Path):
    """Read one extruded mesh and convert it directly to the generic ``HydroMesh``."""
    return load_extruded_mesh(path).to_hydro_mesh()


def save_hydro_mesh_vtu(hydro_mesh, path: str | Path) -> Path:
    """Write a ``HydroMesh`` to a VTU file (any topology, 2D or 3D)."""
    from hydromodpy.mesh.io import write_vtu

    return write_vtu(path, hydro_mesh)


def load_hydro_mesh_vtu(path: str | Path):
    """Read a ``HydroMesh`` from a VTU file."""
    from hydromodpy.mesh.io import read_vtu

    return read_vtu(path)

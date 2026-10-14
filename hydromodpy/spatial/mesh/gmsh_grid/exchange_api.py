"""Expose the simplest public I/O API for planar meshes and the ``HydroMesh``.

This module is the entry point to use when a caller only needs to load or save
a 2D planar mesh, or to move a ``HydroMesh`` through a VTU file. It deliberately
hides the lower-level implementation modules so colleagues can work with a
small and stable surface.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D


def load_planar_mesh(path: str | Path, *, cell_type: str | None = None) -> GmshPlanarMesh2D:
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


# ---------------------------------------------------------------------------
# Unified HydroMesh bridge
# ---------------------------------------------------------------------------


def load_planar_as_hydro_mesh(path: str | Path, *, cell_type: str | None = None):
    """Read one planar mesh and convert it directly to the generic ``HydroMesh``."""
    return load_planar_mesh(path, cell_type=cell_type).to_hydro_mesh()


def save_hydro_mesh_vtu(hydro_mesh, path: str | Path) -> Path:
    """Write a ``HydroMesh`` to a VTU file (any topology, 2D or 3D)."""
    from hydromodpy.spatial.mesh.io import write_vtu

    return write_vtu(path, hydro_mesh)


def load_hydro_mesh_vtu(path: str | Path):
    """Read a ``HydroMesh`` from a VTU file."""
    from hydromodpy.spatial.mesh.io import read_vtu

    return read_vtu(path)

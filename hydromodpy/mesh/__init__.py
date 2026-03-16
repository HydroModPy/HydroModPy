"""Unified mesh pivot for HydroModPy.

This package provides ``HydroMesh``, a single data container that represents
both structured and unstructured grids in 2D and 3D.  Every mesh producer
(gmsh, flopy, field module) can convert to ``HydroMesh``, and every mesh
consumer (plotting, solver adapters, I/O) can consume it.

Quick start::

    from hydromodpy.mesh import HydroMesh, CellBlock, CellType

    mesh = HydroMesh(
        vertices=points_xy,
        cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),),
    )

Adapters::

    from hydromodpy.mesh.adapters import from_meshio, to_meshio
    from hydromodpy.mesh.adapters import from_gmsh_planar, from_extruded_prism
    from hydromodpy.mesh.adapters import from_flopy_structured, to_flopy_disv_args

I/O::

    from hydromodpy.mesh.io import read_vtu, write_vtu

Plotting::

    from hydromodpy.mesh.plotting import plot_cell_values
"""

from hydromodpy.mesh.cell_types import CellType
from hydromodpy.mesh.hydro_mesh import CellBlock, HydroMesh

__all__ = (
    "CellType",
    "CellBlock",
    "HydroMesh",
)

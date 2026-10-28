"""Shape, pitch and vertices of the regular grid, bit for bit the flopy ones.

The solvers used to read the vertices back from ``flopy.StructuredGrid``. The
engine now computes them with the same floating-point operations, so a run keeps
its coordinates, its DIS file and its cell centres to the last bit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.request import RasterGridSpec

__all__ = ["GridLayout", "plan_layout", "quad_mesh"]

PITCH_RTOL = 1.0e-9
"""Relative gap under which a requested size equals the DEM pitch."""


@dataclass(frozen=True)
class GridLayout:
    """Where the regular grid sits: its shape, its pitch [m] and its lower-left corner."""

    nrow: int
    ncol: int
    dx: float
    dy: float
    xoff: float
    yoff: float
    native: bool


def plan_layout(
    grid: RasterGridSpec, nominal_size_m: float, options: Mapping[str, object]
) -> GridLayout:
    """Choose the shape and the pitch of the regular grid.

    ``options["shape"]`` fixes the shape. Without it the grid is the DEM grid
    when ``nominal_size_m`` equals its pitch, and a coarser one otherwise. A
    shape equal to the DEM shape is the DEM grid, whatever way it was asked for:
    ``Surface.resample_to_shape`` returns the surface unchanged then. The native
    pitch is the DEM pitch; a resampled grid spans the DEM bounds, the rule of
    ``Surface.resample_to_shape``. The shape is ``[nrow, ncol]``, as
    ``[mesh.regular] shape`` gives it.
    """
    shape = options.get("shape")
    if shape is None:
        h = float(nominal_size_m)
        if abs(h - grid.dx) <= PITCH_RTOL * grid.dx and abs(h - grid.dy) <= PITCH_RTOL * grid.dy:
            shape = (grid.nrow, grid.ncol)
        else:
            if h < min(grid.dx, grid.dy) * (1.0 - PITCH_RTOL):
                raise MeshRequestError(
                    f"the regular engine cannot mesh finer than the DEM: cell size {h} m, "
                    f"DEM pitch {grid.dx} x {grid.dy} m"
                )
            shape = (
                max(1, round((grid.ymax - grid.ymin) / h)),
                max(1, round((grid.xmax - grid.xmin) / h)),
            )
    nrow, ncol = (int(n) for n in shape)
    native = (nrow, ncol) == (grid.nrow, grid.ncol)
    if native:
        dx, dy = grid.dx, grid.dy
    else:
        dx = (grid.xmax - grid.xmin) / ncol
        dy = (grid.ymax - grid.ymin) / nrow
    return GridLayout(nrow, ncol, dx, dy, grid.xmin, grid.ymin, native)


def quad_mesh(layout: GridLayout) -> HydroMesh:
    """Return the quads of the layout, row 0 north, nodes ``[NW, NE, SE, SW]``.

    The vertex arithmetic is the one of ``flopy.discretization.StructuredGrid``
    (``xvertices``, ``yvertices`` at a zero rotation).
    """
    nrow, ncol = layout.nrow, layout.ncol
    delr = np.full(ncol, layout.dx)
    delc = np.full(nrow, layout.dy)
    x_edges = np.concatenate(([0.0], np.add.accumulate(delr)))
    total_dy = np.add.reduce(delc)
    y_edges = np.concatenate(([total_dy], total_dy - np.add.accumulate(delc)))
    xg, yg = np.meshgrid(x_edges, y_edges)
    xg = xg + layout.xoff
    yg = yg + layout.yoff
    # flopy rotates by zero about (xoff, yoff): cos = 1 and sin = 0 are exact,
    # but the round trip through the offset is a floating-point operation.
    xv = layout.xoff + (xg - layout.xoff)
    yv = layout.yoff + (yg - layout.yoff)
    vertices = np.column_stack((xv.reshape(-1), yv.reshape(-1)))

    nx = ncol + 1
    j, i = np.divmod(np.arange(nrow * ncol), ncol)
    n00 = j * nx + i
    n01 = (j + 1) * nx + i
    connectivity = np.column_stack([n00, n00 + 1, n01 + 1, n01]).astype(int)
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        structured_shape=(nrow, ncol),
    )

"""The :class:`RegularGrid` wrapper of a DEM-aligned structured grid.

:class:`RegularGrid` describes DIS / structured-in-plan grids built from a DEM
raster transform (uniform cell size, ``(nrow, ncol)`` shape). It is a purely
data-carrying wrapper around :class:`HydroMesh`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh


@dataclass(frozen=True, slots=True)
class RegularGrid:
    """Structured-in-plan grid backed by a uniform DEM raster.

    ``shape`` follows the raster convention ``(nrow, ncol)``. ``origin`` is
    the upper-left corner ``(xmin, ymax)`` consistent with row-zero-on-top
    rasters; ``dx``/``dy`` are positive cell sizes along x/y.
    """

    shape: tuple[int, int]
    dx: float
    dy: float
    origin: tuple[float, float]
    n_layers: int = 1
    crs: str | None = None

    @property
    def topology(self) -> str:
        return "regular"

    @property
    def n_cells(self) -> int:
        return int(self.shape[0]) * int(self.shape[1])

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        nrow, ncol = self.shape
        xmin, ymax = self.origin
        return (xmin, ymax - nrow * self.dy, xmin + ncol * self.dx, ymax)

    def to_hydro_mesh(self) -> HydroMesh:
        nrow, ncol = int(self.shape[0]), int(self.shape[1])
        xmin, ymax = self.origin
        x_edges = xmin + np.arange(ncol + 1, dtype=float) * float(self.dx)
        y_edges = ymax - np.arange(nrow + 1, dtype=float) * float(self.dy)
        x_v, y_v = np.meshgrid(x_edges, y_edges, indexing="xy")
        vertices = np.column_stack((x_v.reshape(-1), y_v.reshape(-1)))
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


__all__ = ("RegularGrid",)

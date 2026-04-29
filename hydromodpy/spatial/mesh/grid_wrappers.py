"""Concrete implementations of the :class:`Grid` Protocol.

Three wrappers cover the topologies HydroModPy recognises:

* :class:`RegularGrid` - DIS / structured-in-plan grids built from a DEM
  raster transform (uniform cell size, ``(nrow, ncol)`` shape).
* :class:`IrregularGrid` - DISV planar meshes carrying explicit vertices and
  face-node connectivity (typically Gmsh triangulations).
* :class:`LumpedGrid` - sentinel for lumped models such as GR4J. A
  :class:`HydroMesh` cannot be materialised: :meth:`to_hydro_mesh` raises.

These are purely data-carrying wrappers around :class:`HydroMesh`. They expose
the topology property required by downstream readers (``Run.grid`` /
``Run.fields`` / ``Run.mesh``) without changing the storage layout.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh


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
        connectivity = np.empty((nrow * ncol, 4), dtype=int)
        idx = 0
        for j in range(nrow):
            for i in range(ncol):
                n00 = j * nx + i
                n10 = j * nx + (i + 1)
                n11 = (j + 1) * nx + (i + 1)
                n01 = (j + 1) * nx + i
                connectivity[idx] = [n00, n10, n11, n01]
                idx += 1
        return HydroMesh(
            vertices=vertices,
            cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
            structured_shape=(nrow, ncol),
        )


@dataclass(frozen=True, slots=True)
class IrregularGrid:
    """Unstructured-in-plan grid (DISV) backed by an explicit :class:`HydroMesh`."""

    mesh: HydroMesh
    n_layers: int = 1
    crs: str | None = None

    @property
    def topology(self) -> str:
        return "irregular"

    @property
    def n_cells(self) -> int:
        return int(self.mesh.n_cells)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        b = self.mesh.bounds()
        # bounds returns (xmin, ymin, xmax, ymax) in 2D
        if len(b) == 4:
            xmin, ymin, xmax, ymax = b
        else:
            xmin, ymin, _, xmax, ymax, _ = b
        return (xmin, ymin, xmax, ymax)

    def to_hydro_mesh(self) -> HydroMesh:
        return self.mesh


@dataclass(frozen=True, slots=True)
class LumpedGrid:
    """Single-cell sentinel for lumped catchment models (GR4J).

    A lumped run has no spatial discretisation. Calling :meth:`to_hydro_mesh`
    raises :class:`RuntimeError` to make the contract violation explicit.
    """

    crs: str | None = None

    @property
    def topology(self) -> str:
        return "lumped"

    @property
    def n_cells(self) -> int:
        return 1

    @property
    def n_layers(self) -> int:
        return 1

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        raise RuntimeError("lumped simulation has no spatial bbox")

    def to_hydro_mesh(self) -> HydroMesh:
        raise RuntimeError("lumped simulation has no spatial grid")


__all__ = ("IrregularGrid", "LumpedGrid", "RegularGrid")

"""Shared spatial-grid abstractions for MODFLOW-family solvers."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np

from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface


@dataclass(frozen=True, slots=True)
class GridReference:
    """Minimal geometric description of one solver grid.

    Works for both structured and unstructured grids.  Structured grids
    set ``structured_shape`` to ``(nrow, ncol)`` which enables raster
    exports and DIS package construction.
    """

    n_cells: int
    bounds: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
    crs: str | None
    nodata: float = -9999.0
    structured_shape: tuple[int, int] | None = None
    cell_size_hint: float | None = None

    @property
    def is_structured(self) -> bool:
        return self.structured_shape is not None

    @property
    def nrow(self) -> int:
        if self.structured_shape is None:
            raise ValueError("nrow is only available for structured grids")
        return self.structured_shape[0]

    @property
    def ncol(self) -> int:
        if self.structured_shape is None:
            raise ValueError("ncol is only available for structured grids")
        return self.structured_shape[1]

    @property
    def shape(self) -> tuple[int, int]:
        return (self.nrow, self.ncol)

    @property
    def xmin(self) -> float:
        return self.bounds[0]

    @property
    def ymin(self) -> float:
        return self.bounds[1]

    @property
    def xmax(self) -> float:
        return self.bounds[2]

    @property
    def ymax(self) -> float:
        return self.bounds[3]

    @property
    def dx(self) -> float:
        if self.structured_shape is None:
            if self.cell_size_hint is not None:
                return self.cell_size_hint
            raise ValueError("dx is only available for structured grids")
        return (self.xmax - self.xmin) / self.ncol

    @property
    def dy(self) -> float:
        if self.structured_shape is None:
            if self.cell_size_hint is not None:
                return self.cell_size_hint
            raise ValueError("dy is only available for structured grids")
        return (self.ymax - self.ymin) / self.nrow

    @property
    def cell_area(self) -> float:
        return float(self.dx) * float(self.dy)

    @property
    def characteristic_length(self) -> float:
        return sqrt(self.cell_area)

    def to_raster_support(self) -> RasterSupport:
        """Convert to RasterSupport (structured only)."""
        return RasterSupport(
            crs=self.crs,
            dx=float(self.dx),
            dy=float(self.dy),
            xmin=float(self.xmin),
            xmax=float(self.xmax),
            ymin=float(self.ymin),
            ymax=float(self.ymax),
            nrows=self.nrow,
            ncols=self.ncol,
            nodata=float(self.nodata),
        )

    @classmethod
    def from_surface(
        cls,
        surface: Surface,
        *,
        nodata: float | None = None,
    ) -> GridReference:
        support = surface.support
        if support is None:
            raise ValueError("surface.support is required to build GridReference")
        support.assert_complete_domain()
        return cls(
            n_cells=int(support.nrows) * int(support.ncols),
            bounds=(
                float(support.xmin),
                float(support.ymin),
                float(support.xmax),
                float(support.ymax),
            ),
            crs=None if support.crs is None else str(support.crs),
            nodata=float(
                support.nodata
                if nodata is None and support.nodata is not None
                else (-9999.0 if nodata is None else nodata)
            ),
            structured_shape=(int(support.nrows), int(support.ncols)),
            cell_size_hint=float(support.dx),
        )

    @classmethod
    def from_solver_mesh(
        cls,
        solver_mesh: SolverMesh,
        *,
        crs: str | None = None,
        nodata: float = -9999.0,
    ) -> GridReference:
        """Build from a SolverMesh."""
        mesh_bounds = solver_mesh.planar_mesh.bounds()
        xmin, ymin = float(mesh_bounds[0]), float(mesh_bounds[1])
        xmax, ymax = float(mesh_bounds[2]), float(mesh_bounds[3])
        return cls(
            n_cells=solver_mesh.n_cells,
            bounds=(xmin, ymin, xmax, ymax),
            crs=crs,
            nodata=float(nodata),
            structured_shape=solver_mesh.structured_shape,
            cell_size_hint=float(solver_mesh.characteristic_length),
        )


@dataclass(slots=True)
class SolverGridContext:
    """Runtime bundle for one solver grid (structured or unstructured)."""

    grid: GridReference
    solver_mesh: SolverMesh
    top_surface: Surface
    bottom_surface: Surface
    template_raster_path: str | None = None

    @property
    def top_elevation(self) -> np.ndarray:
        """Top elevation as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.top, dtype=float)

    @property
    def bottom_layer(self) -> np.ndarray:
        """Bottom elevation of deepest layer as flat (n_cells,) array."""
        return np.asarray(self.solver_mesh.botm[-1], dtype=float)

    @property
    def nlay(self) -> int:
        return self.solver_mesh.nlay

    @property
    def n_cells(self) -> int:
        return self.solver_mesh.n_cells

    @property
    def is_structured(self) -> bool:
        return self.solver_mesh.is_structured

    @property
    def nrow(self) -> int:
        return self.solver_mesh.nrow

    @property
    def ncol(self) -> int:
        return self.solver_mesh.ncol

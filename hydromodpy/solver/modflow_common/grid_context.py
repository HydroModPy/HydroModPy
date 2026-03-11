"""Shared spatial-grid abstractions for MODFLOW-family solvers."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np

from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface


@dataclass(frozen=True, slots=True)
class GridReference:
    """Minimal geometric description of one solver grid."""

    nrow: int
    ncol: int
    dx: float
    dy: float
    xmin: float
    ymin: float
    crs: str | None
    nodata: float = -9999.0

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.nrow), int(self.ncol))

    @property
    def xmax(self) -> float:
        return float(self.xmin) + float(self.ncol) * float(self.dx)

    @property
    def ymax(self) -> float:
        return float(self.ymin) + float(self.nrow) * float(self.dy)

    @property
    def cell_area(self) -> float:
        return float(self.dx) * float(self.dy)

    @property
    def characteristic_length(self) -> float:
        return sqrt(self.cell_area)

    def to_raster_support(self) -> RasterSupport:
        return RasterSupport(
            crs=self.crs,
            dx=float(self.dx),
            dy=float(self.dy),
            xmin=float(self.xmin),
            xmax=float(self.xmax),
            ymin=float(self.ymin),
            ymax=float(self.ymax),
            nrows=int(self.nrow),
            ncols=int(self.ncol),
            nodata=float(self.nodata),
        )

    @classmethod
    def from_surface(
        cls,
        surface: Surface,
        *,
        nodata: float | None = None,
    ) -> "GridReference":
        support = surface.support
        if support is None:
            raise ValueError("surface.support is required to build GridReference")
        support.assert_complete_domain()
        return cls(
            nrow=int(support.nrows),
            ncol=int(support.ncols),
            dx=float(support.dx),
            dy=float(support.dy),
            xmin=float(support.xmin),
            ymin=float(support.ymin),
            crs=None if support.crs is None else str(support.crs),
            nodata=float(
                support.nodata
                if nodata is None and support.nodata is not None
                else (-9999.0 if nodata is None else nodata)
            ),
        )

    @classmethod
    def from_sgrid(
        cls,
        sgrid: object,
        *,
        nodata: float = -9999.0,
    ) -> "GridReference":
        delr = np.asarray(getattr(sgrid, "delr"), dtype=float).reshape(-1)
        delc = np.asarray(getattr(sgrid, "delc"), dtype=float).reshape(-1)
        if delr.size == 0 or delc.size == 0:
            raise ValueError("sgrid.delr and sgrid.delc must be non-empty")
        return cls(
            nrow=int(getattr(sgrid, "nrow")),
            ncol=int(getattr(sgrid, "ncol")),
            dx=float(np.mean(delr)),
            dy=float(np.mean(delc)),
            xmin=float(getattr(sgrid, "xoffset", getattr(sgrid, "xoff"))),
            ymin=float(getattr(sgrid, "yoffset", getattr(sgrid, "yoff"))),
            crs=None if getattr(sgrid, "crs", None) is None else str(getattr(sgrid, "crs")),
            nodata=float(nodata),
        )


@dataclass(slots=True)
class SolverGridContext:
    """Runtime bundle for one solver-aligned structured grid."""

    grid: GridReference
    top_surface: Surface
    bottom_surface: Surface
    sgrid: object
    zbot: np.ndarray
    inactive_mask: np.ndarray
    template_raster_path: str | None = None

    @property
    def top_elevation(self) -> np.ndarray:
        return np.asarray(self.top_surface.as_array(), dtype=float)

    @property
    def bottom_layer(self) -> np.ndarray:
        return np.asarray(self.zbot[-1], dtype=float)

    @property
    def nlay(self) -> int:
        return int(self.zbot.shape[0])

    @property
    def nrow(self) -> int:
        return int(self.grid.nrow)

    @property
    def ncol(self) -> int:
        return int(self.grid.ncol)

"""
Raster reading utilities for cartesian structured grids.

Why this component is extracted
-------------------------------
- Isolate the ``rasterio`` dependency in one place.
- Keep ``StructuredGridBuilder`` focused on deterministic numeric construction.
- Simplify unit testing by making raster I/O replaceable with a dedicated adapter.
- Reduce future migration cost if raster backend changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import Affine


@dataclass(frozen=True)
class TopRasterGrid:
    """Container for top-raster values and derived horizontal grid metadata."""

    top: np.ndarray
    delc: np.ndarray
    delr: np.ndarray
    xoff: float
    yoff: float
    nrow: int
    ncol: int
    transform: Affine
    crs: Any
    bounds: tuple[float, float, float, float]


class RasterGridReader:
    """Read 2D raster data and derive cartesian-grid metadata."""

    def read_top_grid(self, path: str) -> TopRasterGrid:
        """Read top raster and derive ``StructuredGrid`` horizontal metadata."""
        with rasterio.open(str(path)) as src:
            nrow = src.height
            ncol = src.width
            delc = np.array([src.transform[0]] * nrow)
            delr = np.array([-src.transform[4]] * ncol)
            xoff = src.bounds.left
            yoff = src.bounds.bottom
            top = np.asarray(src.read(1), dtype=float)
            transform = src.transform
            crs = src.crs
            bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
        return TopRasterGrid(
            top=top,
            delc=delc,
            delr=delr,
            xoff=xoff,
            yoff=yoff,
            nrow=nrow,
            ncol=ncol,
            transform=transform,
            crs=crs,
            bounds=bounds,
        )

    def read_band1(self, path: str) -> np.ndarray:
        """Read and return first band as ``float`` array."""
        with rasterio.open(str(path)) as src:
            return np.asarray(src.read(1), dtype=float)

    def read_band1_with_metadata(
        self, path: str
    ) -> tuple[np.ndarray, Affine, Any, tuple[float, float, float, float]]:
        """Read first band and return values, transform, CRS and bounds."""
        with rasterio.open(str(path)) as src:
            values = np.asarray(src.read(1), dtype=float)
            bounds = (src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top)
            return values, src.transform, src.crs, bounds

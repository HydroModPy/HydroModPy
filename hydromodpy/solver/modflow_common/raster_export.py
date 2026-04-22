"""Raster exports based on solver grid geometry rather than a DEM template."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from .grid_context import GridReference


def write_grid_array_to_raster(
    *,
    grid: GridReference,
    data: np.ndarray,
    output_path: str | Path,
    nodata: float | None = None,
) -> str:
    """Write one 2D array on the geometry described by ``grid``."""
    array = np.asarray(data)
    if array.shape != grid.shape:
        raise ValueError(f"Raster export shape mismatch: expected {grid.shape}, got {array.shape}.")

    dst_path = Path(output_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_origin(float(grid.xmin), float(grid.ymax), float(grid.dx), float(grid.dy))

    with rasterio.open(
        dst_path,
        "w",
        driver="GTiff",
        height=int(grid.nrow),
        width=int(grid.ncol),
        count=1,
        dtype=array.dtype,
        crs=grid.crs,
        transform=transform,
        nodata=float(grid.nodata if nodata is None else nodata),
    ) as dst:
        dst.write(array, 1)

    return str(dst_path)

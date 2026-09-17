"""Readbacks every terrain engine owes its products, whatever wrote them.

Counting the cells of a mask and summing the area of a boundary are properties
of the files, not of the engine that emitted them: an engine that computed them
from its own in-memory arrays could report a number the file on disk does not
carry.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio

from hydromodpy.core.exceptions import TerrainProductError

MASK_INSIDE = 1
MASK_NODATA = -32768
"""What the Whitebox watershed tool writes outside the catchment."""


def mask_cell_count(path: str | Path) -> int:
    """Count the cells a mask raster marks as inside."""
    with rasterio.open(str(path)) as src:
        data = src.read(1)
    return int(np.count_nonzero(data == MASK_INSIDE))


def boundary_area_m2(path: str | Path) -> float:
    """Sum the area of every polygon of a boundary layer, in square metres."""
    frame = gpd.read_file(str(path))
    if frame.empty:
        return 0.0
    return float(frame.geometry.area.sum())


def raster_crs(path: str | Path) -> str:
    """Return the CRS a raster carries, as a string, or an empty string."""
    with rasterio.open(str(path)) as src:
        return str(src.crs) if src.crs else ""


def raster_nodata(path: str | Path) -> float:
    """Return the nodata a raster declares, read back from the file.

    Read rather than assumed: the value belongs to whatever wrote the file, and
    a product that declares one the file does not carry is a false declaration.
    """
    with rasterio.open(str(path)) as src:
        if src.nodata is None:
            raise TerrainProductError(f"Raster declares no nodata value: {path}")
        return float(src.nodata)


__all__ = [
    "MASK_INSIDE",
    "MASK_NODATA",
    "boundary_area_m2",
    "mask_cell_count",
    "raster_crs",
    "raster_nodata",
]

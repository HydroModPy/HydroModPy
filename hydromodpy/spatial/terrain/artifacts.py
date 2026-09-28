"""Readbacks every terrain engine owes its products, whatever wrote them.

Counting the cells of a mask and summing the area of a boundary are properties
of the files, not of the engine that emitted them: an engine that computed them
from its own in-memory arrays could report a number the file on disk does not
carry.

For the same reason this module is public rather than private to the package:
a caller describing a product stack it finds on disk, and did not write, has to
read the same facts from the same files.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.errors
import rasterio.windows

from hydromodpy.core.exceptions import TerrainProductError
from hydromodpy.spatial.terrain.port import MASK_INSIDE, MASK_NODATA


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


def raster_max_near(
    path: str | Path, points: Sequence[tuple[float, float]], radius_m: float
) -> float:
    """Return the largest value a raster carries within ``radius_m`` of any point.

    Snapping an outlet ranks the cells of its search window and nothing else, so
    that window is where stored values must still order. A regional raster whose
    main river carries more cells than float32 can tell apart does not stop an
    outlet whose window holds far fewer. The window is the square the snap reads,
    one cell wider on each side. NaN when no point falls on the raster.
    """
    with rasterio.open(str(path)) as src:
        pad = max(abs(src.res[0]), abs(src.res[1]))
        best = float("nan")
        for x, y in points:
            window = rasterio.windows.from_bounds(
                x - radius_m - pad,
                y - radius_m - pad,
                x + radius_m + pad,
                y + radius_m + pad,
                transform=src.transform,
            )
            window = window.round_offsets().round_lengths()
            try:
                window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
            except rasterio.errors.WindowError:
                # The point lies off the raster: the snap has nothing to rank here.
                continue
            data = src.read(1, window=window, masked=True)
            if data.count() == 0:
                continue
            local = float(data.max())
            best = local if not np.isfinite(best) else max(best, local)
    return best


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
    "raster_max_near",
    "raster_nodata",
]

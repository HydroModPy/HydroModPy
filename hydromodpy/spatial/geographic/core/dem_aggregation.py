"""Aggregate the initial DEM to a coarser cell before anything is delineated.

``[geographic.catchment].dem_resolution`` names the cell size the routing
surface, the catchment, the mesh and the model top are built on. The DEM file
keeps its own pixel; the aggregated copy is written once per geographic run
and every later step reads it instead of the file.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

RESOLUTION_TOLERANCE = 1.0e-6
"""Relative gap under which a requested cell size is the DEM's own."""

_DEFAULT_NODATA = -9999.0


def aggregated_dem_filename(resolution_m: float) -> str:
    """Return the file name of the aggregated DEM for one cell size."""
    return f"dem_init_{float(resolution_m):g}m.tif"


def native_resolution(dem_path: str | Path) -> float:
    """Return the pixel size of a north-up DEM, in the units of its CRS."""
    with rasterio.open(str(dem_path)) as src:
        transform = src.transform
        if transform.b != 0.0 or transform.d != 0.0:
            raise ValueError(f"{dem_path}: a rotated DEM cannot be aggregated.")
        return max(abs(float(transform.a)), abs(float(transform.e)))


def aggregate_dem(
    dem_path: str | Path,
    out_path: str | Path,
    *,
    resolution_m: float,
) -> Path:
    """Write ``dem_path`` aggregated to ``resolution_m`` and return the new path.

    Each coarse cell takes the mean of the fine pixels it covers, nodata pixels
    left out. The coarse grid is aligned on the upper-left corner of the DEM and
    covers it whole, so the last row and column may be partial blocks. A cell
    size finer than the DEM's own pixel is refused: a DEM is aggregated, never
    refined.
    """
    target = float(resolution_m)
    if not target > 0.0:
        raise ValueError(f"dem_resolution = {target:g} m: a cell size is a positive length.")
    with rasterio.open(str(dem_path)) as src:
        native = native_resolution(dem_path)
        if target < native * (1.0 - RESOLUTION_TOLERANCE):
            raise ValueError(
                f"dem_resolution = {target:g} m is finer than the {native:g} m pixel of "
                f"{Path(dem_path).name}: a DEM is aggregated, never refined. Give a cell "
                "size at least the DEM's own, or a finer DEM."
            )
        nodata = float(src.nodata) if src.nodata is not None else _DEFAULT_NODATA
        width = math.ceil(src.width * abs(float(src.transform.a)) / target)
        height = math.ceil(src.height * abs(float(src.transform.e)) / target)
        dst_transform = from_origin(float(src.transform.c), float(src.transform.f), target, target)
        source = src.read(1).astype(np.float64)
        if src.nodata is None:
            source = np.where(np.isfinite(source), source, nodata)
        destination = np.full((height, width), nodata, dtype=np.float64)
        reproject(
            source=source,
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=src.crs,
            src_nodata=nodata,
            dst_nodata=nodata,
            resampling=Resampling.average,
        )
        profile = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": 1,
            "dtype": "float32",
            "crs": src.crs,
            "transform": dst_transform,
            "nodata": nodata,
            "compress": "deflate",
        }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(str(out), "w", **profile) as dst:
        dst.write(destination.astype(np.float32), 1)
    logger.info(
        "DEM aggregated from %g m to %g m: %d x %d pixels to %d x %d, mean of the fine pixels.",
        native,
        target,
        src.width,
        src.height,
        width,
        height,
    )
    return out

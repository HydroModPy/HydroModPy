"""Convert a DEM raster into HydroModPy domain surface objects.

Purpose
-------
Bridge geospatial raster metadata (transform, CRS, nodata) with HydroModPy
domain abstractions (``RasterSupport`` and ``Surface``).

Pipeline position
-----------------
Used once a DEM support is ready and must be injected into domain execution.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface


def build_surface_topo_from_dem(dem_path: str | Path) -> Surface:
    """Build a topographic ``Surface`` from one DEM file.

    The function reads the first DEM band, reconstructs georeferencing bounds
    from the affine transform, then builds a ``RasterSupport`` consumed by the
    domain ``Surface`` abstraction.
    """
    raster_path = Path(dem_path)
    if not raster_path.exists():
        raise FileNotFoundError(f"DEM not found: {raster_path}")

    with rasterio.open(str(raster_path)) as src:
        values = np.asarray(src.read(1), dtype=float)
        transform = src.transform
        nodata = src.nodata

        x_pixel = values.shape[1]
        y_pixel = values.shape[0]
        resolution_x = float(transform.a)
        resolution_y = float(transform.e)

        xmin = float(transform.c)
        ymax = float(transform.f)
        xmax = xmin + x_pixel * resolution_x
        ymin = ymax + y_pixel * resolution_y

        georeferencing = {
            "crs": src.crs.to_string() if src.crs is not None else None,
            "dx": abs(resolution_x),
            "dy": abs(resolution_y),
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
        }

    support = RasterSupport.from_georeferencing(
        georeferencing,
        shape=values.shape,
        nodata=nodata,
    )
    return Surface.from_geographic_dem(values, support=support)

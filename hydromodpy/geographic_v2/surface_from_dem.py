"""Build a domain ``Surface`` object from one DEM raster file."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface


def build_surface_topo_from_dem(dem_path: str | Path) -> Surface:
    """Read one DEM raster and convert it to a `Surface` with georeferencing support."""
    # Step 1 - Validate input path.
    raster_path = Path(dem_path)
    if not raster_path.exists():
        raise FileNotFoundError(f"DEM not found: {raster_path}")

    # Step 2 - Read DEM values and georeferencing primitives.
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

        # Normalize metadata to the RasterSupport georeferencing contract.
        georeferencing = {
            "crs": src.crs.to_string() if src.crs is not None else None,
            "dx": abs(resolution_x),
            "dy": abs(resolution_y),
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
        }

    # Step 3 - Build raster support and domain surface object.
    support = RasterSupport.from_georeferencing(
        georeferencing,
        shape=values.shape,
        nodata=nodata,
    )
    return Surface.from_geographic_dem(values, support=support)

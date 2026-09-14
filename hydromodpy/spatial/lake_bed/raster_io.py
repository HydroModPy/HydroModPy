"""Read a bathymetry raster (GeoTIFF/ASC) into a :class:`Surface`.

The lake-bed reconstruction needs the bathymetry as a georeferenced array it can
sample at mesh-cell locations. The data layer hands over a raster file path; this
loader turns it into a :class:`~hydromodpy.spatial.surface.Surface` (values plus
``RasterSupport``) so the rest of the pipeline stays pure ``spatial``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface

__all__ = ["load_surface_from_raster"]


def load_surface_from_raster(path: str | Path, *, name: str = "lake_bathymetry") -> Surface:
    """Load a single-band raster file into a north-up :class:`Surface`.

    The returned surface stores the band as a ``(nrows, ncols)`` array with row 0
    at the northern edge (``ymax``), matching the convention used by
    :class:`~hydromodpy.spatial.surface_sampling.PreparedSurfaceSampler`. Nodata
    pixels keep their sentinel; the sampler turns them into ``NaN``.
    """
    import rasterio

    raster_path = Path(str(path)).resolve()
    if not raster_path.exists():
        raise FileNotFoundError(f"lake bathymetry raster not found: {raster_path}")

    with rasterio.open(str(raster_path)) as src:
        values = np.asarray(src.read(1), dtype=float)
        bounds = src.bounds
        nrows = int(src.height)
        ncols = int(src.width)
        crs = str(src.crs) if src.crs else None
        nodata = None if src.nodata is None else float(src.nodata)

    xmin = float(bounds.left)
    xmax = float(bounds.right)
    ymin = float(bounds.bottom)
    ymax = float(bounds.top)
    support = RasterSupport(
        crs=crs,
        dx=(xmax - xmin) / ncols,
        dy=(ymax - ymin) / nrows,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        nrows=nrows,
        ncols=ncols,
        nodata=nodata,
    )
    return Surface(name=name, values=values, support=support)

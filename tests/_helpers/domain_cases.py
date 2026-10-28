"""Grids, surfaces and masks shared by the tests of ``hydromodpy.spatial.domain``.

A test says what differs from one small Lambert-93 grid: its shape, its cell,
its values. The grid sits at (X0, Y0) in its south-west corner.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface

CRS = "EPSG:2154"
NODATA = -9999.0
X0, Y0 = 350_000.0, 6_790_000.0


def raster_support(
    nrows: int,
    ncols: int,
    *,
    cell: float = 25.0,
    x0: float = X0,
    y0: float = Y0,
    crs: str = CRS,
    nodata: float | None = NODATA,
) -> RasterSupport:
    """Return the support of a north-up grid whose south-west corner is (x0, y0)."""
    return RasterSupport(
        crs=crs, dx=cell, dy=cell, xmin=x0, xmax=x0 + ncols * cell, ymin=y0,
        ymax=y0 + nrows * cell, nrows=nrows, ncols=ncols, nodata=nodata,
    )  # fmt: skip


def surface(values, *, name: str = "surface_topo", **grid) -> Surface:
    """Return a surface carrying *values* on the grid ``raster_support`` builds."""
    array = np.asarray(values, dtype=float)
    return Surface(name=name, values=array, support=raster_support(*array.shape, **grid))


def tilted_top(nrows: int = 6, ncols: int = 8) -> Surface:
    """Return a plane rising 2 m per column and falling 1.5 m per row."""
    rows, cols = np.mgrid[0:nrows, 0:ncols]
    return surface(100.0 + 2.0 * cols - 1.5 * rows)


def write_mask(path: Path, layers: dict[str, tuple[float, ...]], *, crs: str | None = CRS) -> Path:
    """Write one GeoPackage holding one box polygon per layer."""
    import geopandas as gpd
    from shapely.geometry import box

    for index, (layer, bounds) in enumerate(layers.items()):
        gpd.GeoDataFrame({"site_id": [layer]}, geometry=[box(*bounds)], crs=crs).to_file(
            str(path), driver="GPKG", layer=layer, mode="w" if index == 0 else "a"
        )
    return path

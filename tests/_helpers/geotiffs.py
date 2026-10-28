"""One GeoTIFF writer for the tests.

The tests of the spatial layers write small rasters on disk. They all go
through ``write_geotiff``, so a test only says what differs: the values,
where the grid sits, its cell size, its CRS and its nodata.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_geotiff(
    path: Path | str,
    array: np.ndarray,
    *,
    origin: tuple[float, float] | None = None,
    cell: float | tuple[float, float] = 1.0,
    crs: str | None = "EPSG:2154",
    nodata: float | None = None,
    dtype: str | np.dtype | None = None,
) -> Path:
    """Write *array* as a GeoTIFF and return its path.

    A 2-D array is one band, a 3-D array is ``(bands, rows, cols)``.
    *origin* is the (west, north) corner of the grid. It defaults to
    ``(0, rows * cell_y)``, so the grid starts at (0, 0) in the south-west.
    *cell* is the pixel size, one value for square pixels or ``(x, y)``.
    The parent folder is created.
    """
    import rasterio
    from rasterio.transform import from_origin

    data = np.asarray(array)
    if dtype is not None:
        data = data.astype(dtype)
    bands = data[np.newaxis] if data.ndim == 2 else data
    cell_x, cell_y = (float(cell), float(cell)) if np.isscalar(cell) else map(float, cell)
    if origin is None:
        origin = (0.0, bands.shape[1] * cell_y)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=bands.shape[1], width=bands.shape[2],
        count=bands.shape[0], dtype=bands.dtype, crs=crs, nodata=nodata,
        transform=from_origin(float(origin[0]), float(origin[1]), cell_x, cell_y),
    ) as dst:  # fmt: skip
        dst.write(bands)
    return path

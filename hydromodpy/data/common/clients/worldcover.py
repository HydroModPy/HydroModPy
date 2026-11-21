"""ESA WorldCover: the 10 m class map of a box, read by window from the public tiles.

WorldCover is served as cloud-optimised GeoTIFF tiles of 3 by 3 degrees on a public
bucket, so a request reads only the window of its box, in a few seconds. The sealed
share and the curve number both read the class map. The network and raster libraries
are imported inside the functions.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import DataProductError, NetworkError

if TYPE_CHECKING:
    import numpy as np
    from affine import Affine

    from hydromodpy.core.runtime.bounds import Bounds

WORLDCOVER_ORIGIN = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
"""The bucket ``fetch`` answers of, for the :class:`FileRecord` it returns."""

VERSIONS: dict[int, str] = {2020: "v100", 2021: "v200"}
TILE_DEGREES = 3


def tile_names(bbox: tuple[float, float, float, float]) -> list[str]:
    """Names of the tiles that meet ``bbox`` (lon/lat), such as ``N48W003``."""
    names = []
    lat_start = math.floor(bbox[1] / TILE_DEGREES) * TILE_DEGREES
    lon_start = math.floor(bbox[0] / TILE_DEGREES) * TILE_DEGREES
    for lat in range(lat_start, math.ceil(bbox[3] / TILE_DEGREES) * TILE_DEGREES, TILE_DEGREES):
        for lon in range(lon_start, math.ceil(bbox[2] / TILE_DEGREES) * TILE_DEGREES, TILE_DEGREES):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            names.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
    return names


def tile_url(name: str, year: int) -> str:
    """URL of one WorldCover map tile."""
    version = VERSIONS[year]
    return f"{WORLDCOVER_ORIGIN}/{version}/{year}/map/ESA_WorldCover_10m_{year}_{version}_{name}_Map.tif"


def worldcover_classes(
    bbox: tuple[float, float, float, float], year: int, *, bounds: Bounds | None = None
) -> tuple[np.ndarray, Affine]:
    """The WorldCover class of each 10 m pixel of ``bbox`` (EPSG:4326), 0 where none, and its grid."""
    import rasterio
    from rasterio.merge import merge

    from hydromodpy.core.io.fetch import open_client, vsicurl_path

    if year not in VERSIONS:
        raise DataProductError(f"WorldCover has maps for {sorted(VERSIONS)}, not {year}.")
    paths = []
    with open_client(bounds=bounds) as http:
        for name in tile_names(bbox):
            try:
                paths.append(vsicurl_path(tile_url(name, year), bounds=bounds, client=http))
            except NetworkError as exc:
                # The bucket has no tile over open sea.
                if "404" not in str(exc):
                    raise
    if not paths:
        raise DataProductError(f"WorldCover {year} has no tile over the box {bbox}.")
    datasets = [rasterio.open(path) for path in paths]
    try:
        classes, transform = merge(datasets, bounds=bbox, nodata=0)
    finally:
        for dataset in datasets:
            dataset.close()
    return classes[0], transform


__all__ = [
    "TILE_DEGREES",
    "VERSIONS",
    "WORLDCOVER_ORIGIN",
    "tile_names",
    "tile_url",
    "worldcover_classes",
]

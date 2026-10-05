"""Geoplateforme WMS-Raster client for elevation grids.

The service draws any bounding box at any pixel size, in EPSG:2154, and answers a
float32 GeoTIFF whose values are metres. The server refuses an image wider or
taller than ``MAX_IMAGE_PX`` pixels, so a large box is cut into tiles that line up
on the output grid and are fetched one by one. Product-specific choices (which
layer, which resolutions, the cache) belong in ``ign_dem_fr.py``.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import requests

from hydromodpy.data.variables.dem.apis.geoplateforme_download import (
    GeoPlateformeDownloadError,
    RateLimiter,
    default_session,
    request_with_retries,
)

WMS_URL = "https://data.geopf.fr/wms-r/wms"
MAX_IMAGE_PX = 5010
"""``MaxWidth`` and ``MaxHeight`` of the capabilities; 5011 is answered with HTTP 400."""
DEFAULT_TILE_PX = 2500
"""Tile side. Well under the limit so that a retry costs 25 MB, not 100 MB."""
_TIFF_MAGIC = (b"II*\x00", b"MM\x00*")
_TILE_ATTEMPTS = 2
"""A tile whose body cannot be read is asked once more before it is an error."""


@dataclass(frozen=True)
class WmsTile:
    """One request of the plan: its place in the output grid and its box."""

    col_off: int
    row_off: int
    width: int
    height: int
    bbox: tuple[float, float, float, float]


def snap_bbox(
    bbox: tuple[float, float, float, float], resolution_m: float
) -> tuple[float, float, float, float]:
    """Grow ``bbox`` outward to multiples of ``resolution_m``.

    The pixels then sit on the native grid of the product, and two requests of the
    same resolution always share their pixel edges.
    """
    xmin, ymin, xmax, ymax = (float(v) for v in bbox)
    res = float(resolution_m)
    return (
        math.floor(xmin / res) * res,
        math.floor(ymin / res) * res,
        math.ceil(xmax / res) * res,
        math.ceil(ymax / res) * res,
    )


def grid_shape(bbox: tuple[float, float, float, float], resolution_m: float) -> tuple[int, int]:
    """Return ``(rows, cols)`` of a box already snapped to the grid."""
    res = float(resolution_m)
    return round((bbox[3] - bbox[1]) / res), round((bbox[2] - bbox[0]) / res)


def plan_tiles(
    bbox: tuple[float, float, float, float],
    resolution_m: float,
    *,
    tile_px: int = DEFAULT_TILE_PX,
) -> Iterator[WmsTile]:
    """Cut a snapped box into tiles of at most ``tile_px`` pixels per side."""
    if not 0 < tile_px <= MAX_IMAGE_PX:
        raise ValueError(f"tile_px must be in 1..{MAX_IMAGE_PX}, got {tile_px}.")
    res = float(resolution_m)
    rows, cols = grid_shape(bbox, res)
    for row_off in range(0, rows, tile_px):
        height = min(tile_px, rows - row_off)
        for col_off in range(0, cols, tile_px):
            width = min(tile_px, cols - col_off)
            x0 = bbox[0] + col_off * res
            y1 = bbox[3] - row_off * res
            yield WmsTile(
                col_off=col_off,
                row_off=row_off,
                width=width,
                height=height,
                bbox=(x0, y1 - height * res, x0 + width * res, y1),
            )


def fetch_tile(
    layer: str,
    tile: WmsTile,
    *,
    session: requests.Session | None = None,
    timeout: float = 120.0,
    rate_limiter: RateLimiter | None = None,
) -> np.ndarray:
    """Return the elevation of one tile as float32, nodata as NaN.

    The server writes nodata as -99999 and, where it resamples next to it, blends
    it into the neighbouring values; anything at or below -9990 is nodata here.

    The answer is checked against the request: a server that answers 200 with an
    XML exception, or with a grid that is not the one asked for, is an error here,
    never a hole in the mosaic.
    """
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "CRS": "EPSG:2154",
        "BBOX": ",".join(repr(float(v)) for v in tile.bbox),
        "WIDTH": tile.width,
        "HEIGHT": tile.height,
        "FORMAT": "image/geotiff",
    }
    for attempt in range(_TILE_ATTEMPTS):
        response = request_with_retries(
            session or default_session(),
            WMS_URL,
            params=params,
            timeout=timeout,
            rate_limiter=rate_limiter,
        )
        try:
            return _read_answer(response.content, layer, tile)
        except _UnreadableAnswer as exc:
            if attempt == _TILE_ATTEMPTS - 1:
                raise GeoPlateformeDownloadError(str(exc)) from exc
    raise AssertionError("unreachable")  # pragma: no cover


class _UnreadableAnswer(Exception):
    """The body is a GeoTIFF that GDAL cannot read to the end (truncated, corrupt)."""


def _read_answer(payload: bytes, layer: str, tile: WmsTile) -> np.ndarray:
    from rasterio.errors import RasterioIOError
    from rasterio.io import MemoryFile

    if not payload.startswith(_TIFF_MAGIC):
        raise GeoPlateformeDownloadError(
            f"WMS-Raster did not answer a GeoTIFF for {layer} {tile.bbox}: "
            f"{payload[:300].decode('utf-8', 'replace')!r}"
        )
    try:
        with MemoryFile(payload) as memory, memory.open() as source:
            if (source.width, source.height) != (tile.width, tile.height):
                raise GeoPlateformeDownloadError(
                    f"WMS-Raster answered {source.width}x{source.height} pixels, "
                    f"asked {tile.width}x{tile.height}, for {tile.bbox}."
                )
            origin = (source.transform.c, source.transform.f)
            if abs(origin[0] - tile.bbox[0]) > 1e-6 or abs(origin[1] - tile.bbox[3]) > 1e-6:
                raise GeoPlateformeDownloadError(
                    f"WMS-Raster answered a grid starting at {origin}, "
                    f"asked ({tile.bbox[0]}, {tile.bbox[3]})."
                )
            data = source.read(1).astype("float32")
    except RasterioIOError as exc:
        raise _UnreadableAnswer(
            f"WMS-Raster answered a GeoTIFF that cannot be read for {layer} {tile.bbox}: {exc}"
        ) from exc
    data[(data <= -9990.0) | ~np.isfinite(data)] = np.nan
    return data

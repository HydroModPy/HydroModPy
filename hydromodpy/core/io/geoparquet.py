"""OGC GeoParquet 1.1 atomic writer."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Final

from hydromodpy.core.io.atomic import replace_with_retry
from hydromodpy.core.io.filesystem import native_io_path

if TYPE_CHECKING:
    import geopandas as gpd

GEOPARQUET_SCHEMA_VERSION: Final[str] = "1.1.0"
"""OGC GeoParquet contract used for every vector file produced by v2."""

GEOPARQUET_WRITE_DEFAULTS: Final[dict[str, object]] = {
    "compression": "zstd",
    "compression_level": 5,
    "schema_version": GEOPARQUET_SCHEMA_VERSION,
    "geometry_encoding": "WKB",
    "write_covering_bbox": True,
    "index": False,
}
"""Canonical write options applied by :func:`write_geoparquet_atomic`."""


def write_geoparquet_atomic(
    gdf: gpd.GeoDataFrame,
    target: Path | str,
) -> Path:
    """Persist ``gdf`` as an OGC GeoParquet 1.1 file atomically."""
    target = Path(target)
    os.makedirs(native_io_path(target.parent), exist_ok=True)
    if gdf.crs is None:
        raise ValueError("GeoParquet writer requires gdf.crs to be set")
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
    tmp_io = native_io_path(tmp)
    target_io = native_io_path(target)
    if os.path.exists(tmp_io):
        os.unlink(tmp_io)
    try:
        gdf.to_parquet(tmp_io, **GEOPARQUET_WRITE_DEFAULTS)
    except Exception:
        try:
            os.unlink(tmp_io)
        except FileNotFoundError:
            pass
        raise
    replace_with_retry(tmp_io, target_io)
    return target


def read_geoparquet(target: Path | str) -> gpd.GeoDataFrame:
    """Read a GeoParquet file via :func:`geopandas.read_parquet`."""
    import geopandas as gpd_mod

    return gpd_mod.read_parquet(native_io_path(target))


__all__ = [
    "GEOPARQUET_SCHEMA_VERSION",
    "GEOPARQUET_WRITE_DEFAULTS",
    "read_geoparquet",
    "write_geoparquet_atomic",
]

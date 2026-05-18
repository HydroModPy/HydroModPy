"""OGC GeoParquet 1.1 atomic writer.

Wraps :meth:`geopandas.GeoDataFrame.to_parquet` with the v2 defaults:
schema version ``1.1.0``, WKB geometry encoding, bbox covering column for
spatial predicate pushdown, ZSTD level 5 compression. The write is staged on
a sibling ``.tmp-<uuid>`` file then atomically promoted via ``os.replace`` so
readers never observe a partial Parquet on disk.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Final

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
    """Persist ``gdf`` as a OGC GeoParquet 1.1 file atomically.

    Parameters
    ----------
    gdf
        Vector layer to write. CRS must be set on the GeoDataFrame; the OGC
        ``geo`` metadata key is populated from it by geopandas.
    target
        Destination path. Parent directory is created on demand.

    Returns
    -------
    Path
        The resolved ``target`` path after the rename.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if gdf.crs is None:
        raise ValueError("GeoParquet writer requires gdf.crs to be set")
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
    if tmp.exists():
        tmp.unlink()
    try:
        gdf.to_parquet(tmp, **GEOPARQUET_WRITE_DEFAULTS)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, target)
    return target


def read_geoparquet(target: Path | str) -> gpd.GeoDataFrame:
    """Read a GeoParquet file via :func:`geopandas.read_parquet`."""
    import geopandas as gpd_mod

    return gpd_mod.read_parquet(Path(target))


__all__ = [
    "GEOPARQUET_SCHEMA_VERSION",
    "GEOPARQUET_WRITE_DEFAULTS",
    "read_geoparquet",
    "write_geoparquet_atomic",
]

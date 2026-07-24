"""Convert user-facing vector files into OGC GeoParquet 1.1 vector tables.

Accepted inputs: Shapefile (``*.shp``), GeoJSON (``*.geojson``),
GeoPackage (``*.gpkg``) and already-GeoParquet files (passthrough).
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from hydromodpy.core.exceptions import DataError
from hydromodpy.core.io.geoparquet import GEOPARQUET_WRITE_DEFAULTS

VECTOR_SUFFIXES = frozenset({".shp", ".geojson", ".json", ".gpkg", ".parquet"})


class VectorConversionError(DataError):
    """Raised when a vector file cannot be converted."""


def convert_vector_to_geoparquet(
    src: str | Path,
    dest: str | Path,
    *,
    layer: str | None = None,
) -> Path:
    """Convert a vector file to a GeoParquet 1.1 table.

    Uses :meth:`geopandas.GeoDataFrame.to_parquet` with
    ``schema_version=1.1.0``, ``geometry_encoding=WKB`` and
    ``write_covering_bbox=True``. If geopandas/pyogrio is not installed,
    passthrough GeoParquet input (simple copy) and raise for other formats so
    the caller can decide what to do.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.exists():
        raise FileNotFoundError(src)

    if src.suffix.lower() not in VECTOR_SUFFIXES:
        raise VectorConversionError(
            f"Unsupported vector suffix {src.suffix!r} (expected one of {sorted(VECTOR_SUFFIXES)})"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        import geopandas as gpd  # type: ignore
    except ModuleNotFoundError:
        if src.suffix.lower() == ".parquet":
            shutil.copyfile(src, dest)
            return dest
        raise VectorConversionError(
            f"geopandas is required to convert non-Parquet vector files; cannot convert {src.name}"
        ) from None

    if src.suffix.lower() == ".parquet":
        # GeoParquet is read with the native reader. gpd.read_file would route
        # through the GDAL Parquet driver, which many GDAL builds ship without,
        # so a perfectly valid GeoParquet would fail to ingest.
        gdf = gpd.read_parquet(src)
    else:
        read_kwargs = {"layer": layer} if layer else {}
        gdf = gpd.read_file(src, **read_kwargs)
    if gdf.crs is None:
        raise VectorConversionError(
            f"{src} has no CRS; add a .prj sidecar or set gdf.crs before ingest"
        )
    tmp = dest.with_name(f"{dest.name}.tmp-{uuid.uuid4().hex}")
    try:
        gdf.to_parquet(tmp, **GEOPARQUET_WRITE_DEFAULTS)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    os.replace(tmp, dest)
    return dest

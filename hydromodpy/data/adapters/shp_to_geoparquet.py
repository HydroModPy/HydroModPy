"""Convert user-facing vector files into Parquet vector tables.

Accepted inputs: Shapefile (``*.shp``), GeoJSON (``*.geojson``),
GeoPackage (``*.gpkg``) and already-GeoParquet files (passthrough).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.core.exceptions import DataError

VECTOR_SUFFIXES = frozenset({".shp", ".geojson", ".json", ".gpkg", ".parquet"})


class VectorConversionError(DataError):
    """Raised when a vector file cannot be converted."""


def convert_vector_to_geoparquet(
    src: str | Path,
    dest: str | Path,
    *,
    layer: str | None = None,
) -> Path:
    """Convert a vector file to a Parquet table with WKB geometry.

    If geopandas/pyogrio is not installed, passthrough GeoParquet input
    (simple copy) and raise for other formats so the caller can decide
    what to do.
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

    read_kwargs = {"layer": layer} if layer else {}
    gdf = gpd.read_file(src, **read_kwargs)
    if gdf.crs is None:
        raise VectorConversionError(
            f"{src} has no CRS; add a .prj sidecar or set gdf.crs before ingest"
        )
    import duckdb

    frame = gdf.drop(columns=[gdf.geometry.name]).copy()
    for column in frame.columns:
        frame[column] = frame[column].map(_plain_value)
    frame["crs"] = str(gdf.crs)
    frame["geometry_wkb"] = [
        None if geom is None or geom.is_empty else bytes(geom.wkb) for geom in gdf.geometry
    ]
    frame["geometry_type"] = [
        None if geom is None or geom.is_empty else str(geom.geom_type) for geom in gdf.geometry
    ]
    tmp = dest.with_name(dest.name + ".tmp")
    conn = duckdb.connect(":memory:")
    try:
        conn.register("_hmp_vector", frame)
        tmp_sql = str(tmp).replace("'", "''")
        conn.execute(f"COPY (SELECT * FROM _hmp_vector) TO '{tmp_sql}' (FORMAT PARQUET)")
    finally:
        conn.close()
    tmp.replace(dest)
    return dest


def _plain_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

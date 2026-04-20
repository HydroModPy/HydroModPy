"""Convert user-facing vector files into GeoParquet.

Accepted inputs: Shapefile (``*.shp``), GeoJSON (``*.geojson``),
GeoPackage (``*.gpkg``) and already-GeoParquet files (passthrough).
"""

from __future__ import annotations

import shutil
from pathlib import Path

VECTOR_SUFFIXES = frozenset({".shp", ".geojson", ".json", ".gpkg", ".parquet"})


class VectorConversionError(RuntimeError):
    """Raised when a vector file cannot be converted."""


def convert_vector_to_geoparquet(
    src: str | Path,
    dest: str | Path,
    *,
    layer: str | None = None,
) -> Path:
    """Convert a vector file to GeoParquet.

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
            "geopandas is required to convert non-Parquet vector files; "
            f"cannot convert {src.name}"
        )

    read_kwargs = {"layer": layer} if layer else {}
    gdf = gpd.read_file(src, **read_kwargs)
    if gdf.crs is None:
        raise VectorConversionError(
            f"{src} has no CRS; add a .prj sidecar or set gdf.crs before ingest"
        )
    gdf.to_parquet(dest)
    return dest

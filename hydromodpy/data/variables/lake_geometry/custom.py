"""Custom lake-geometry data loader.

Normalises a user-provided vector file (SHP/GPKG/GeoJSON) into the internal
GeoParquet pivot and returns a :class:`FieldRecord` pointing at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.data.adapters import convert_vector_to_geoparquet
from hydromodpy.data.contracts.spatial_field import FieldRecord

logger = get_logger(__name__)


def load_custom_lake_geometry(
    source_cfg: Any,
    *,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load a custom lake-geometry vector file as a :class:`FieldRecord`.

    Parameters
    ----------
    source_cfg : source config with a ``path`` attribute
    data_dir : cache directory for the GeoParquet pivot output

    Returns
    -------
    List of one FieldRecord pointing to the loaded/cached file.
    """
    import geopandas as gpd

    path = Path(str(source_cfg.path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Custom lake-geometry path not found: {path}")

    gdf = gpd.read_file(str(path))
    if gdf.empty:
        raise ValueError(f"Custom lake-geometry file is empty: {path}")

    if gdf.crs:
        crs = str(gdf.crs)
    else:
        crs = str(getattr(source_cfg, "default_crs", "EPSG:2154"))
        logger.warning(
            "Custom lake-geometry file %s carries no CRS; using default_crs=%s. Set "
            "data.lake_geometry.sources[].default_crs for a non-French site.",
            path,
            crs,
        )
    bbox = tuple(gdf.total_bounds)

    if data_dir is not None:
        output_path = data_dir / f"lake_geometry_custom_{path.stem}.parquet"
        convert_vector_to_geoparquet(path, output_path)
        data: Path = output_path
    else:
        data = path

    return [
        FieldRecord(
            variable="lake_geometry",
            source="custom",
            unit="-",
            data=data,
            bbox=bbox,
            crs=crs,
        )
    ]

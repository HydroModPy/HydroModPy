"""Vector I/O helpers (shapefile / GeoPackage / GeoParquet)."""

from __future__ import annotations

import logging

import geopandas as gpd

logger = logging.getLogger(__name__)


def load_shapefile(shapefile_path: str) -> gpd.GeoDataFrame | None:
    """Load a vector file (shapefile, GeoPackage, GeoJSON, ...) as a
    :class:`~geopandas.GeoDataFrame`.

    Returns ``None`` and logs the exception when the file cannot be read,
    so callers can decide whether to abort or skip.
    """
    try:
        return gpd.read_file(shapefile_path)
    except Exception:
        logger.exception("Failed to load vector file %s", shapefile_path)
        return None


__all__ = ["load_shapefile"]

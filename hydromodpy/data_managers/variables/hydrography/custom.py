"""Load hydrography data from a local file or directory."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from hydromodpy.support.tools import get_logger

from hydromodpy.data_managers.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)

_VECTOR_EXTENSIONS = ("*.shp", "*.gpkg", "*.geojson")
_RASTER_EXTENSIONS = ("*.tif", "*.tiff")


def load_custom(config: HydrographySourceConfig) -> gpd.GeoDataFrame | Path:
    """Read a local file pointed to by *config.path*.

    Returns a ``GeoDataFrame`` for vector files (SHP/GPKG/GeoJSON) or a
    ``Path`` for raster files (TIF/TIFF).  The manager handles the raster
    pipeline separately.
    """
    path = Path(config.path)

    if path.is_dir():
        # Try raster first, then vector
        candidates: list[Path] = []
        for ext in _RASTER_EXTENSIONS:
            candidates.extend(path.glob(ext))
        if candidates:
            path = candidates[0]
            logger.info("Auto-detected raster file: %s", path)
            return path

        for ext in _VECTOR_EXTENSIONS:
            candidates.extend(path.glob(ext))
        if not candidates:
            all_exts = _VECTOR_EXTENSIONS + _RASTER_EXTENSIONS
            raise FileNotFoundError(
                f"No vector or raster file ({', '.join(all_exts)}) found in {config.path}"
            )
        path = candidates[0]
        logger.info("Auto-detected vector file: %s", path)

    # Single file — decide by extension
    if path.suffix.lower() in (".tif", ".tiff"):
        logger.info("Loading custom hydrography raster from %s", path)
        return path

    logger.info("Loading custom hydrography vector from %s", path)
    return gpd.read_file(path)

"""Custom lake-bathymetry data loader.

Normalises a user-provided raster (GeoTIFF/ASC) into a COG GeoTIFF pivot and
returns a :class:`FieldRecord` pointing at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.data.adapters import convert_asc_to_geotiff
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.provenance.derived import derived_path

logger = get_logger(__name__)


def load_custom_lake_bathymetry(
    source_cfg: Any,
    *,
    derived_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load a custom lake-bathymetry raster as a :class:`FieldRecord`.

    Parameters
    ----------
    source_cfg : source config with a ``path`` attribute
    derived_dir : directory for the COG GeoTIFF pivot.
        It is never the user's data folder: a derived copy named like a
        user file would be taken for one.

    Returns
    -------
    List of one FieldRecord pointing to the loaded/cached file.
    """
    import rasterio

    path = Path(str(source_cfg.path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Custom lake-bathymetry path not found: {path}")

    with rasterio.open(str(path)) as src:
        bounds = src.bounds
        if src.crs:
            crs = str(src.crs)
        else:
            crs = str(getattr(source_cfg, "default_crs", "EPSG:2154"))
            logger.warning(
                "Custom lake-bathymetry raster %s carries no CRS; using default_crs=%s. "
                "Set data.lake_bathymetry.sources[].default_crs for a non-French site.",
                path,
                crs,
            )
        bbox = (bounds.left, bounds.bottom, bounds.right, bounds.top)

    if derived_dir is not None:
        output_path = derived_path(derived_dir, path, kind="cog", suffix=".tif")
        convert_asc_to_geotiff(path, output_path)
        data: Path = output_path
    else:
        data = path

    return [
        FieldRecord(
            variable="lake_bathymetry",
            source="custom",
            unit="m",
            data=data,
            bbox=bbox,
            crs=crs,
        )
    ]

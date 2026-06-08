"""Custom lake-bathymetry data loader.

Normalises a user-provided raster (GeoTIFF/ASC) into a COG GeoTIFF pivot and
returns a :class:`FieldRecord` pointing at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.adapters import convert_asc_to_geotiff
from hydromodpy.data.contracts.spatial_field import FieldRecord


def load_custom_lake_bathymetry(
    source_cfg: Any,
    *,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load a custom lake-bathymetry raster as a :class:`FieldRecord`.

    Parameters
    ----------
    source_cfg : source config with a ``path`` attribute
    data_dir : cache directory for the COG GeoTIFF pivot output

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
        crs = str(src.crs) if src.crs else "EPSG:2154"
        bbox = (bounds.left, bounds.bottom, bounds.right, bounds.top)

    if data_dir is not None:
        output_path = data_dir / f"lake_bathymetry_custom_{path.stem}.tif"
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

"""Convert Esri ASCII grids (.asc) to Cloud Optimized GeoTIFF.

Also passes through native GeoTIFF inputs (``.tif``/``.tiff``) with a
validation step that ensures they carry a CRS. COG-specific tiling is
applied when rasterio is available; otherwise the input is copied
verbatim and the caller decides whether to proceed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.core.exceptions import DataError


class RasterConversionError(DataError):
    """Raised when a raster file cannot be converted to COG."""


RASTER_SUFFIXES = frozenset({".asc", ".tif", ".tiff"})


def convert_asc_to_geotiff(
    src: str | Path,
    dest: str | Path,
) -> Path:
    """Convert an ASC or GeoTIFF raster to a COG-style GeoTIFF.

    ``dest`` should end with ``.tif``. Raises
    :class:`RasterConversionError` when the source has no CRS metadata.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.exists():
        raise FileNotFoundError(src)
    if src.suffix.lower() not in RASTER_SUFFIXES:
        raise RasterConversionError(
            f"Unsupported raster suffix {src.suffix!r} (expected one of {sorted(RASTER_SUFFIXES)})"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        import rasterio  # type: ignore
    except ModuleNotFoundError:
        if src.suffix.lower() in (".tif", ".tiff"):
            shutil.copyfile(src, dest)
            return dest
        raise RasterConversionError(
            "rasterio is required to convert ASC to GeoTIFF; "
            f"cannot convert {src.name}"
        )

    with rasterio.open(src) as ds:
        if ds.crs is None:
            raise RasterConversionError(
                f"{src} has no CRS; add a .prj sidecar before ingest"
            )
        data = ds.read()
        profile = ds.profile

    profile.update(
        driver="GTiff",
        compress="zstd",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    with rasterio.open(dest, "w", **profile) as out:
        out.write(data)
    return dest

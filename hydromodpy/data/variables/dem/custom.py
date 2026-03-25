"""Custom DEM data loaders.

Supports:
- TIF/TIFF: GeoTIFF raster elevation files
- ASC: Esri ASCII Grid elevation files (converted to GeoTIFF on load)
- NC: NetCDF elevation datasets
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.data.contracts.spatial_field import FieldRecord


def load_custom_dem(
    source_cfg: Any,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load custom DEM data from a user-provided path.

    Parameters
    ----------
    source_cfg : source config with ``path`` attribute
    bbox : optional bounding box for cropping
    data_dir : cache directory for processed outputs

    Returns
    -------
    List of FieldRecord pointing to the loaded/cached file.
    """
    path = Path(str(source_cfg.path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Custom DEM path not found: {path}")

    if path.is_dir():
        path = _find_dem_file_in_dir(path)

    ext = path.suffix.strip().lower()

    if ext in (".tif", ".tiff"):
        return _load_raster(path, bbox=bbox)
    elif ext == ".asc":
        return _load_asc(path, bbox=bbox, data_dir=data_dir)
    elif ext == ".nc":
        return _load_netcdf(path, bbox=bbox)
    else:
        raise ValueError(
            f"Unsupported custom DEM format: '{ext}'. "
            "Supported: .tif, .tiff, .asc, .nc"
        )


def _find_dem_file_in_dir(directory: Path) -> Path:
    """Find a single DEM file in a directory."""
    for ext in (".tif", ".tiff", ".asc", ".nc"):
        candidates = list(directory.glob(f"*{ext}"))
        if candidates:
            return candidates[0]
    raise FileNotFoundError(
        f"No DEM file (TIF, ASC, NC) found in {directory}"
    )


def _load_raster(
    path: Path,
    *,
    bbox: tuple | None = None,
) -> list[FieldRecord]:
    """Load a GeoTIFF DEM file as FieldRecord."""
    import rasterio

    with rasterio.open(str(path)) as src:
        bounds = src.bounds
        crs = str(src.crs) if src.crs else "EPSG:2154"
        actual_bbox = (bounds.left, bounds.bottom, bounds.right, bounds.top)

    return [FieldRecord(
        variable="dem", source="custom",
        unit="m", data=path,
        bbox=actual_bbox, crs=crs,
    )]


def _load_asc(
    path: Path,
    *,
    bbox: tuple | None = None,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Load an Esri ASCII Grid DEM and convert to GeoTIFF."""
    import rasterio

    with rasterio.open(str(path)) as src:
        bounds = src.bounds
        crs = str(src.crs) if src.crs else "EPSG:2154"
        actual_bbox = (bounds.left, bounds.bottom, bounds.right, bounds.top)

        # Convert to GeoTIFF for faster future reads.
        if data_dir is not None:
            output_path = data_dir / f"dem_custom_{path.stem}.tif"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            profile = src.profile.copy()
            profile.update(driver="GTiff", compress="deflate")
            with rasterio.open(str(output_path), "w", **profile) as dst:
                dst.write(src.read())
            data = output_path
        else:
            data = path

    return [FieldRecord(
        variable="dem", source="custom",
        unit="m", data=data,
        bbox=actual_bbox, crs=crs,
    )]


def _load_netcdf(
    path: Path,
    *,
    bbox: tuple | None = None,
) -> list[FieldRecord]:
    """Load a NetCDF DEM as FieldRecord."""
    import xarray as xr

    ds = xr.open_dataset(str(path))

    # Try to find elevation variable.
    elev_var = None
    for name in ("elevation", "dem", "z", "altitude", "height", "Band1"):
        if name in ds.data_vars:
            elev_var = name
            break
    if elev_var is None and len(ds.data_vars) == 1:
        elev_var = list(ds.data_vars)[0]
    if elev_var is None:
        raise ValueError(
            f"Cannot identify elevation variable in {path}. "
            f"Available: {list(ds.data_vars)}"
        )

    # Resolve spatial bounds.
    x_name = None
    for name in ("x", "X", "lon", "longitude", "easting"):
        if name in ds.coords:
            x_name = name
            break
    y_name = None
    for name in ("y", "Y", "lat", "latitude", "northing"):
        if name in ds.coords:
            y_name = name
            break

    if x_name and y_name:
        x_vals = ds.coords[x_name].values
        y_vals = ds.coords[y_name].values
        actual_bbox = (
            float(x_vals.min()), float(y_vals.min()),
            float(x_vals.max()), float(y_vals.max()),
        )
    else:
        actual_bbox = bbox or (0, 0, 0, 0)

    crs = str(ds.attrs.get("crs", ds.attrs.get("proj4", "EPSG:2154")))

    return [FieldRecord(
        variable="dem", source="custom",
        unit="m", data=path,
        bbox=actual_bbox, crs=crs,
    )]

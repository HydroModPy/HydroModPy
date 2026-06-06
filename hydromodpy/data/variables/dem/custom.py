"""Custom DEM data loaders.

Supports:
- TIF/TIFF: GeoTIFF raster elevation files
- ASC: Esri ASCII Grid elevation files (converted to GeoTIFF on load)
- NC: NetCDF elevation datasets
"""

from __future__ import annotations

import hashlib
import json
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
        paths = _find_dem_files_in_dir(path)
        if len(paths) > 1:
            return _load_raster_mosaic(paths, bbox=bbox, data_dir=data_dir)
        path = paths[0]

    ext = path.suffix.strip().lower()

    if ext in (".tif", ".tiff"):
        return _load_raster(path, bbox=bbox)
    elif ext == ".asc":
        return _load_asc(path, bbox=bbox, data_dir=data_dir)
    elif ext == ".nc":
        return _load_netcdf(path, bbox=bbox)
    else:
        raise ValueError(
            f"Unsupported custom DEM format: '{ext}'. Supported: .tif, .tiff, .asc, .nc"
        )


def _find_dem_files_in_dir(directory: Path) -> list[Path]:
    """Find DEM files in a directory, skipping scaffold examples."""
    from hydromodpy.data.common.io_helpers import is_scaffold_example

    candidates: list[Path] = []
    for ext in (".tif", ".tiff", ".asc", ".nc"):
        candidates.extend(
            p for p in sorted(directory.glob(f"*{ext}")) if not is_scaffold_example(p)
        )
    if candidates:
        return candidates
    raise FileNotFoundError(
        f"No DEM file (TIF, ASC, NC) found in {directory}. "
        "EXAMPLE templates are ignored: add your own file or point 'path' at it."
    )


def _find_dem_file_in_dir(directory: Path) -> Path:
    """Find the first DEM file in a directory."""
    return _find_dem_files_in_dir(directory)[0]


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

    return [
        FieldRecord(
            variable="dem",
            source="custom",
            unit="m",
            data=path,
            bbox=actual_bbox,
            crs=crs,
        )
    ]


def _load_raster_mosaic(
    paths: list[Path],
    *,
    bbox: tuple | None = None,
    data_dir: Path | None = None,
) -> list[FieldRecord]:
    """Merge several local raster DEM tiles into a cached GeoTIFF."""
    raster_paths = [path for path in paths if path.suffix.strip().lower() in {".tif", ".tiff", ".asc"}]
    unsupported = [path for path in paths if path not in raster_paths]
    if unsupported:
        names = ", ".join(path.name for path in unsupported)
        raise ValueError(
            "Multiple custom DEM files can only be mosaicked for .tif, .tiff and .asc "
            f"tiles. Unsupported in multi-file directory: {names}"
        )
    if data_dir is None:
        raise ValueError("Multiple custom DEM files require a data_dir for the cached mosaic.")

    output_path = _mosaic_cache_path(raster_paths, bbox=bbox, data_dir=data_dir)
    if output_path.exists():
        return _load_raster(output_path, bbox=bbox)

    import rasterio
    from rasterio.merge import merge

    datasets = []
    try:
        for path in raster_paths:
            datasets.append(rasterio.open(str(path)))
        crs_values = {str(dataset.crs) for dataset in datasets if dataset.crs}
        if len(crs_values) > 1:
            raise ValueError(
                "Multiple custom DEM files must share the same CRS before mosaicking. "
                f"Found: {sorted(crs_values)}"
            )
        mosaic, transform = merge(datasets, bounds=bbox)
        profile = datasets[0].profile.copy()
    finally:
        for dataset in datasets:
            dataset.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(
        driver="GTiff",
        height=mosaic.shape[1],
        width=mosaic.shape[2],
        count=mosaic.shape[0],
        transform=transform,
        compress="deflate",
    )
    with rasterio.open(str(output_path), "w", **profile) as dst:
        dst.write(mosaic)

    return _load_raster(output_path, bbox=bbox)


def _mosaic_cache_path(
    paths: list[Path],
    *,
    bbox: tuple | None,
    data_dir: Path,
) -> Path:
    payload = {
        "bbox": list(bbox) if bbox is not None else None,
        "tiles": [
            {
                "path": str(path.resolve()),
                "mtime_ns": path.stat().st_mtime_ns,
                "size": path.stat().st_size,
            }
            for path in paths
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return data_dir / "custom_mosaics" / f"dem_custom_mosaic_{digest}.tif"


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

    return [
        FieldRecord(
            variable="dem",
            source="custom",
            unit="m",
            data=data,
            bbox=actual_bbox,
            crs=crs,
        )
    ]


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
            f"Cannot identify elevation variable in {path}. Available: {list(ds.data_vars)}"
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
            float(x_vals.min()),
            float(y_vals.min()),
            float(x_vals.max()),
            float(y_vals.max()),
        )
    else:
        actual_bbox = bbox or (0, 0, 0, 0)

    crs = str(ds.attrs.get("crs", ds.attrs.get("proj4", "EPSG:2154")))

    return [
        FieldRecord(
            variable="dem",
            source="custom",
            unit="m",
            data=path,
            bbox=actual_bbox,
            crs=crs,
        )
    ]

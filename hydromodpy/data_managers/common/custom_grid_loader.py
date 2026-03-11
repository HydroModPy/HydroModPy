"""Common loaders for custom gridded data (NetCDF and GeoTIFF).

These return FieldRecord instances that can be used by any variable manager.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hydromodpy.data_managers.contracts.spatial_field import FieldRecord


def load_custom_nc(
    path: Path,
    *,
    variable: str,
    unit: str,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Load a custom NetCDF file as FieldRecord(s).

    Extracts spatial bounds and time range from the dataset.
    If *project_period* is given, clips the temporal dimension.
    """
    import xarray as xr

    ds = xr.open_dataset(path)

    # --- Spatial bounds ---
    bbox, crs = _extract_bbox_and_crs(ds)

    # --- Temporal bounds ---
    time_dim = _find_time_dim(ds)
    if time_dim is not None and time_dim in ds.dims:
        if project_period is not None:
            ds = ds.sel(
                {time_dim: slice(
                    project_period[0].isoformat(),
                    project_period[1].isoformat(),
                )},
            )
        times = ds[time_dim].values
        import pandas as pd
        date_start = pd.Timestamp(times[0]).to_pydatetime()
        date_end = pd.Timestamp(times[-1]).to_pydatetime()
        frequency = "D"
    else:
        date_start = None
        date_end = None
        frequency = None

    return [FieldRecord(
        variable=variable,
        source="custom",
        unit=unit,
        data=ds,
        bbox=bbox,
        crs=crs,
        date_start=date_start,
        date_end=date_end,
        frequency=frequency,
    )]


def load_custom_tif(
    path: Path,
    *,
    variable: str,
    unit: str,
) -> list[FieldRecord]:
    """Load a custom GeoTIFF as a static FieldRecord (no temporal dimension).

    Typical use: steady-state heterogeneous fields (e.g. spatial recharge,
    soil properties).
    """
    import rioxarray  # noqa: F401 — registers the rio accessor
    import xarray as xr

    da = xr.open_dataarray(path, engine="rasterio")

    # Extract CRS
    crs = str(da.rio.crs) if da.rio.crs is not None else "EPSG:4326"

    # Extract bounding box (xmin, ymin, xmax, ymax)
    bounds = da.rio.bounds()  # (left, bottom, right, top)
    bbox = (bounds[0], bounds[1], bounds[2], bounds[3])

    # Wrap in Dataset
    ds = da.to_dataset(name=variable)

    return [FieldRecord(
        variable=variable,
        source="custom",
        unit=unit,
        data=ds,
        bbox=bbox,
        crs=crs,
        date_start=None,
        date_end=None,
        frequency=None,
    )]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _extract_bbox_and_crs(ds) -> tuple[tuple, str]:
    """Extract bounding box and CRS from an xarray Dataset."""
    crs = "EPSG:4326"

    # Try rioxarray CRS
    try:
        import rioxarray  # noqa: F401
        if hasattr(ds, "rio") and ds.rio.crs is not None:
            crs = str(ds.rio.crs)
            bounds = ds.rio.bounds()
            return (bounds[0], bounds[1], bounds[2], bounds[3]), crs
    except ImportError:
        pass

    # Fallback: common spatial coordinate names
    x_coord = _find_coord(ds, ("x", "lon", "longitude", "LAMBX", "X"))
    y_coord = _find_coord(ds, ("y", "lat", "latitude", "LAMBY", "Y"))

    if x_coord is not None and y_coord is not None:
        x_vals = ds[x_coord].values
        y_vals = ds[y_coord].values
        bbox = (
            float(x_vals.min()), float(y_vals.min()),
            float(x_vals.max()), float(y_vals.max()),
        )
        # Heuristic: if coords look like degrees, assume WGS84
        if abs(x_vals.max()) <= 180 and abs(y_vals.max()) <= 90:
            crs = "EPSG:4326"
        return bbox, crs

    return (0.0, 0.0, 0.0, 0.0), crs


def _find_coord(ds, candidates: tuple[str, ...]) -> str | None:
    """Find the first matching coordinate name (case-insensitive)."""
    ds_coords = {c.lower(): c for c in ds.coords}
    for name in candidates:
        if name.lower() in ds_coords:
            return ds_coords[name.lower()]
    return None


def _find_time_dim(ds) -> str | None:
    """Find the time dimension in an xarray Dataset."""
    for name in ("time", "t", "datetime", "date", "TIME"):
        if name in ds.dims:
            return name
    # Check for datetime64 dtype
    for dim in ds.dims:
        if hasattr(ds[dim], "dtype") and "datetime" in str(ds[dim].dtype):
            return dim
    return None

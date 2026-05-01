"""Spatial-mean reductions of FieldRecords for homogeneous fallback series."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_grid_utils import find_xy_dims

if TYPE_CHECKING:
    import xarray as xr


def spatial_mean_one_field(field_rec: Any) -> pd.Series | None:
    """Compute the spatial mean of a single FieldRecord.

    Returns a pd.Series indexed by datetime (mm/day) or None.
    """
    data = field_rec.data

    if isinstance(data, (str, Path)):
        return spatial_mean_from_file(Path(data))

    try:
        import xarray as xr

        if isinstance(data, xr.Dataset):
            return spatial_mean_from_xarray(data)
    except ImportError:
        pass

    return None


def _ensure_finite_source_values(values: object, *, label: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty.")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} must contain only finite numeric values.")
    return arr


def spatial_mean_from_xarray(ds: xr.Dataset) -> pd.Series | None:
    """Spatial mean of an xarray Dataset returned as pd.Series."""
    data_vars = list(ds.data_vars)
    if not data_vars:
        return None
    da = ds[data_vars[0]]
    x_dim, y_dim = find_xy_dims(da)
    del x_dim, y_dim  # values are not needed; identification validates dims.
    _ensure_finite_source_values(da.values, label="recharge gridded forcing values")

    has_time = "time" in da.dims
    if not has_time:
        mean_val = float(da.values.mean())
        return pd.Series([mean_val], index=pd.DatetimeIndex(["2000-01-01"]))

    # Average over spatial dimensions, keep time.
    spatial_dims = [d for d in da.dims if d != "time"]
    mean_ts = da.mean(dim=spatial_dims).values
    time_index = pd.DatetimeIndex(da.coords["time"].values)
    return pd.Series(mean_ts.astype(float), index=time_index)


def spatial_mean_from_file(path: Path) -> pd.Series | None:
    """Spatial mean from a file (NetCDF or GeoTIFF)."""
    suffix = path.suffix.lower()
    if suffix in (".nc", ".nc4", ".netcdf"):
        import xarray as xr

        ds = xr.open_dataset(path)
        try:
            return spatial_mean_from_xarray(ds)
        finally:
            ds.close()

    if suffix in (".tif", ".tiff"):
        try:
            import rasterio

            with rasterio.open(path) as src:
                band = _ensure_finite_source_values(
                    src.read(1),
                    label="recharge GeoTIFF forcing values",
                )
                mean_val = float(np.mean(band))
                return pd.Series([mean_val], index=pd.DatetimeIndex(["2000-01-01"]))
        except ImportError:
            pass

    return None

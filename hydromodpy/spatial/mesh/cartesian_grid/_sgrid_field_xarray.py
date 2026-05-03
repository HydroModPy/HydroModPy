"""xarray and file-based field discretization on structured grids."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_grid_utils import (
    find_xy_dims,
    interp_2d,
)

if TYPE_CHECKING:
    import xarray as xr

logger = get_logger(__name__)

InterpolationMethod = Literal["nearest", "linear", "idw"]


def _ensure_finite_field_values(values: object, *, label: str) -> np.ndarray:
    """Return finite field values as a float array."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ValueError(f"{label} cannot be empty.")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} must contain only finite numeric values.")
    return arr


def discretize_one_field_record(
    field_rec: Any,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Discretize a single FieldRecord onto the solver grid.

    Handles xarray Datasets, file paths (NetCDF, GeoTIFF), and static fields.
    All returned arrays are in m/s.
    """
    from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_grid_utils import (
        unit_to_m_per_s_factor,
    )

    data = field_rec.data
    unit = getattr(field_rec, "unit", "mm/day")
    unit_factor = unit_to_m_per_s_factor(unit)

    if isinstance(data, (str, Path)):
        return discretize_from_file(
            Path(data),
            x_centers=x_centers,
            y_centers=y_centers,
            nrow=nrow,
            ncol=ncol,
            nper=nper,
            period_bounds=period_bounds,
            coverage_policy=coverage_policy,
            unit_factor=unit_factor,
            method=method,
        )

    # xarray Dataset
    try:
        import xarray as xr

        if isinstance(data, xr.Dataset):
            return discretize_from_xarray(
                data,
                x_centers=x_centers,
                y_centers=y_centers,
                nrow=nrow,
                ncol=ncol,
                nper=nper,
                period_bounds=period_bounds,
                coverage_policy=coverage_policy,
                unit_factor=unit_factor,
                method=method,
            )
    except ImportError:
        pass

    logger.warning(
        "Unsupported FieldRecord data type %s for field discretization; returning zeros.",
        type(data).__name__,
    )
    return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}


def discretize_from_xarray(
    ds: xr.Dataset,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Reproject an xarray Dataset onto solver cell centers."""
    # Identify the data variable to use.
    data_vars = list(ds.data_vars)
    if not data_vars:
        return {k: np.zeros((nrow, ncol), dtype=float) for k in range(nper)}
    var_name = data_vars[0]
    da = ds[var_name]

    x_dim, y_dim = find_xy_dims(da)

    has_time = "time" in da.dims
    if not has_time:
        # Static field: apply to all periods.
        source_values = _ensure_finite_field_values(
            da.values,
            label="recharge gridded forcing values",
        )
        arr_2d = (
            interp_2d(
                source_values,
                da.coords[x_dim].values,
                da.coords[y_dim].values,
                x_centers,
                y_centers,
                nrow,
                ncol,
                method,
            )
            * unit_factor
        )
        return {kper: arr_2d.copy() for kper in range(nper)}

    # Time-varying: aggregate per stress period.
    time_coords = pd.DatetimeIndex(da.coords["time"].values)
    results: dict[int, np.ndarray] = {}

    if period_bounds is not None:
        for kper, (t_start, t_end) in enumerate(period_bounds):
            mask = (time_coords >= t_start) & (time_coords < t_end)
            if not mask.any():
                message = (
                    "Recharge coverage check failed: no gridded forcing values inside "
                    f"stress period {kper} [{t_start}, {t_end})."
                )
                if coverage_policy == "error":
                    raise ValueError(message)
                if coverage_policy == "warn":
                    warnings.warn(message, stacklevel=2)
                idx = int(np.argmin(np.abs((time_coords - t_start).total_seconds())))
                slice_2d = _ensure_finite_field_values(
                    da.isel(time=idx).values,
                    label=f"recharge gridded forcing values for stress period {kper}",
                )
            else:
                selected = da.isel(time=mask)
                _ensure_finite_field_values(
                    selected.values,
                    label=f"recharge gridded forcing values for stress period {kper}",
                )
                slice_2d = selected.mean(dim="time").values
            arr_2d = (
                interp_2d(
                    slice_2d,
                    da.coords[x_dim].values,
                    da.coords[y_dim].values,
                    x_centers,
                    y_centers,
                    nrow,
                    ncol,
                    method,
                )
                * unit_factor
            )
            results[kper] = arr_2d
    else:
        # No simulation window: one array per time step.
        for kper in range(min(len(time_coords), 1000)):
            slice_2d = _ensure_finite_field_values(
                da.isel(time=kper).values,
                label=f"recharge gridded forcing values for stress period {kper}",
            )
            arr_2d = (
                interp_2d(
                    slice_2d,
                    da.coords[x_dim].values,
                    da.coords[y_dim].values,
                    x_centers,
                    y_centers,
                    nrow,
                    ncol,
                    method,
                )
                * unit_factor
            )
            results[kper] = arr_2d

    return results


def discretize_from_file(
    path: Path,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Load and discretize from a NetCDF or GeoTIFF file."""
    suffix = path.suffix.lower()
    if suffix in (".nc", ".nc4", ".netcdf"):
        import xarray as xr

        ds = xr.open_dataset(path)
        try:
            return discretize_from_xarray(
                ds,
                x_centers=x_centers,
                y_centers=y_centers,
                nrow=nrow,
                ncol=ncol,
                nper=nper,
                period_bounds=period_bounds,
                coverage_policy=coverage_policy,
                unit_factor=unit_factor,
                method=method,
            )
        finally:
            ds.close()

    if suffix in (".tif", ".tiff"):
        return discretize_geotiff(
            path,
            x_centers=x_centers,
            y_centers=y_centers,
            nrow=nrow,
            ncol=ncol,
            nper=nper,
            period_bounds=period_bounds,
            coverage_policy=coverage_policy,
            unit_factor=unit_factor,
            method=method,
        )

    logger.warning(
        "Unsupported file format '%s' for field discretization; returning zeros.", suffix
    )
    return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}


def discretize_geotiff(
    path: Path,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Read a GeoTIFF (single- or multi-band) and discretize onto solver grid.

    Multi-band GeoTIFFs are treated as temporal: one band per time step.
    """
    try:
        import rasterio
    except ImportError:
        logger.warning("rasterio not available; returning zeros for GeoTIFF field.")
        return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}

    with rasterio.open(path) as src:
        transform = src.transform
        src_nrow, src_ncol = src.height, src.width
        src_x = np.array([transform[2] + (c + 0.5) * transform[0] for c in range(src_ncol)])
        src_y = np.array([transform[5] + (r + 0.5) * transform[4] for r in range(src_nrow)])
        n_bands = src.count

        if n_bands == 1:
            # Static single-band TIF.
            band = _ensure_finite_field_values(
                src.read(1),
                label="recharge GeoTIFF forcing values",
            )
            arr_2d = (
                interp_2d(band, src_x, src_y, x_centers, y_centers, nrow, ncol, method)
                * unit_factor
            )
            return {kper: arr_2d.copy() for kper in range(nper)}

        # Multi-band: one band per time step.
        band_arrays: list[np.ndarray] = []
        for b in range(1, n_bands + 1):
            band = _ensure_finite_field_values(
                src.read(b),
                label=f"recharge GeoTIFF forcing band {b}",
            )
            arr_2d = (
                interp_2d(band, src_x, src_y, x_centers, y_centers, nrow, ncol, method)
                * unit_factor
            )
            band_arrays.append(arr_2d)

    # Map bands to stress periods.
    if period_bounds is not None:
        # Distribute bands evenly across periods; extra bands are averaged.
        results: dict[int, np.ndarray] = {}
        bands_per_period = max(1, len(band_arrays) // len(period_bounds))
        for kper in range(min(nper, len(period_bounds))):
            start_b = kper * bands_per_period
            end_b = min(start_b + bands_per_period, len(band_arrays))
            if start_b >= len(band_arrays):
                message = (
                    "Recharge coverage check failed: no GeoTIFF forcing band mapped to "
                    f"stress period {kper}."
                )
                if coverage_policy == "error":
                    raise ValueError(message)
                if coverage_policy == "warn":
                    warnings.warn(message, stacklevel=2)
                results[kper] = band_arrays[-1].copy()
            else:
                results[kper] = np.mean(band_arrays[start_b:end_b], axis=0)
        return results

    # No simulation window: one band per kper.
    return {kper: band_arrays[kper].copy() for kper in range(min(nper, len(band_arrays)))}

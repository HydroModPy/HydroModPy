"""Field discretization on structured grids (any 2-D climatic variable).

Converts :class:`LoadResult` field records (xarray, NetCDF, GeoTIFF) and
located point records into per-cell 2-D arrays aligned with the MODFLOW
structured grid.

Every public function is **variable-agnostic** and works with any LoadResult
(recharge, precipitation, ETP, temperature, etc.).

Design follows :mod:`sgrid_fieldparam_discretization` patterns but produces
2-D ``(nrow, ncol)`` arrays only (no vertical variation).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from hydromodpy.core.units import factor_to_m_per_s

if TYPE_CHECKING:
    import xarray as xr

    from hydromodpy.core.time import ResolvedSimulationTimeWindow
    from hydromodpy.data.contracts.load_result import LoadResult
    from hydromodpy.data.contracts.spatial_field import FieldRecord
    from hydromodpy.data.contracts.timeseries import PointRecord

logger = logging.getLogger(__name__)

InterpolationMethod = Literal["nearest", "linear", "idw"]


# ------------------------------------------------------------------
# Public entry points
# ------------------------------------------------------------------


def discretize_fields_on_sgrid(
    *,
    load_result: LoadResult,
    sgrid: object,
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Discretize gridded FieldRecords onto a structured MODFLOW grid.

    Parameters
    ----------
    load_result:
        LoadResult containing FieldRecords with gridded recharge data.
        Data units are assumed to be mm/day (data-manager internal unit).
    sgrid:
        Structured grid object providing nrow, ncol, vertex coordinates.
        Accepts both FloPy ``StructuredGrid`` and ``SolverMesh``.
    nper:
        Number of stress periods in the simulation.
    simulation_window:
        Optional time window for temporal alignment of field data.
    method:
        Spatial interpolation method: ``"nearest"``, ``"linear"``, or ``"idw"``.

    Returns
    -------
    dict[int, np.ndarray]
        Mapping ``{kper: array(nrow, ncol)}`` with values in **m/s**
        (consistent with the homogeneous recharge bridge output).
    """
    nrow = int(sgrid.nrow)
    ncol = int(sgrid.ncol)

    if not load_result.has_fields:
        return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}

    # Build target cell-center coordinates from the solver grid.
    x_centers, y_centers = _cell_centers_from_sgrid(sgrid, nrow, ncol)

    # Compute stress-period boundaries for temporal slicing.
    period_bounds = _stress_period_bounds(nper, simulation_window)

    # Aggregate all FieldRecords into one temporal-spatial stack.
    rch_arrays: dict[int, np.ndarray] = {}
    for field_rec in load_result.fields:
        field_arrays = _discretize_one_field_record(
            field_rec,
            x_centers=x_centers,
            y_centers=y_centers,
            nrow=nrow,
            ncol=ncol,
            nper=nper,
            period_bounds=period_bounds,
            method=method,
        )
        for kper, arr in field_arrays.items():
            if kper in rch_arrays:
                # Average when multiple records cover the same period.
                rch_arrays[kper] = 0.5 * (rch_arrays[kper] + arr)
            else:
                rch_arrays[kper] = arr

    # Fill missing periods with zeros.
    for kper in range(nper):
        if kper not in rch_arrays:
            rch_arrays[kper] = np.zeros((nrow, ncol), dtype=float)

    return rch_arrays


def discretize_points_on_sgrid(
    *,
    load_result: LoadResult,
    sgrid: object,
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    method: InterpolationMethod = "nearest",
    source_unit: str = "mm/day",
) -> dict[int, np.ndarray]:
    """Interpolate located PointRecords onto a structured MODFLOW grid.

    Requires each PointRecord to carry a ``location`` with (x, y) coordinates.
    Station values are interpolated onto cell centers per stress period.

    Parameters
    ----------
    load_result:
        LoadResult containing PointRecords with location data.
    sgrid, nper, simulation_window, method:
        Same as :func:`discretize_fields_on_sgrid`.

    Returns
    -------
    dict[int, np.ndarray]
        Mapping ``{kper: array(nrow, ncol)}`` with values in **m/s**.
    """
    from hydromodpy.solver.utils.mesh.cartesian_grid.spatial_interpolation import (
        interpolate_points_to_grid,
    )

    nrow = int(sgrid.nrow)
    ncol = int(sgrid.ncol)

    located_points = _extract_located_points(load_result)
    if not located_points:
        return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}

    x_centers, y_centers = _cell_centers_from_sgrid(sgrid, nrow, ncol)
    period_bounds = _stress_period_bounds(nper, simulation_window)

    station_x = np.array([p.location.x for p in located_points])
    station_y = np.array([p.location.y for p in located_points])

    # Build a time series per station (mm/day).
    station_series: list[pd.Series] = []
    for rec in located_points:
        s = rec.data.set_index("datetime")["value"].sort_index().astype(float)
        station_series.append(s)

    rch_arrays: dict[int, np.ndarray] = {}
    for kper in range(nper):
        # Get the value of each station for this period.
        if period_bounds is not None and kper < len(period_bounds):
            t_start, t_end = period_bounds[kper]
            values = np.array([_period_mean(s, t_start, t_end) for s in station_series])
        else:
            # No temporal alignment: use full-series mean.
            values = np.array([float(s.mean()) for s in station_series])

        # Convert from source unit to m/s.  Per-record unit takes precedence
        # over the caller-supplied default so that mixed-unit datasets work.
        unit_factors = np.array(
            [_unit_to_m_per_s_factor(getattr(p, "unit", source_unit)) for p in located_points]
        )
        values_m_s = values * unit_factors

        arr = interpolate_points_to_grid(
            point_x=station_x,
            point_y=station_y,
            point_values=values_m_s,
            target_x=x_centers,
            target_y=y_centers,
            nrow=nrow,
            ncol=ncol,
            method=method,
        )
        rch_arrays[kper] = arr

    return rch_arrays


def spatial_mean_from_fields(
    load_result: LoadResult,
    *,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> pd.Series | None:
    """Compute the spatial mean of FieldRecords to produce a homogeneous series.

    Reduces gridded data (TIF, NC, xarray) to a single scalar per time step
    by averaging all spatial cells. Returns a pandas Series in mm/day
    (data-manager internal unit) or None if no fields are available.
    """
    if not load_result.has_fields:
        return None

    all_series: list[pd.Series] = []
    for field_rec in load_result.fields:
        s = _spatial_mean_one_field(field_rec)
        if s is not None:
            all_series.append(s)

    if not all_series:
        return None

    if len(all_series) == 1:
        return all_series[0]

    combined = pd.concat(all_series, axis=1)
    return combined.mean(axis=1)


# ------------------------------------------------------------------
# Internal helpers - grid utilities
# ------------------------------------------------------------------


def _cell_centers_from_sgrid(
    sgrid: object,
    nrow: int,
    ncol: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract 2-D arrays of cell-center X and Y coordinates.

    Returns (x_centers, y_centers) each shaped ``(nrow, ncol)``.
    """
    # Prefer explicit cell-center arrays (guarded: FloPy properties may
    # raise when top/botm are not set).
    try:
        xc = getattr(sgrid, "xcellcenters", None)
        yc = getattr(sgrid, "ycellcenters", None)
        if xc is not None and yc is not None:
            xc = np.asarray(xc, dtype=float)
            yc = np.asarray(yc, dtype=float)
            if xc.ndim == 2 and yc.ndim == 2:
                return xc, yc
    except Exception:
        pass

    # Fallback: compute from delr/delc + offsets.
    delr = np.asarray(sgrid.delr, dtype=float).reshape(-1)
    delc = np.asarray(sgrid.delc, dtype=float).reshape(-1)
    xoff = float(getattr(sgrid, "xoffset", getattr(sgrid, "xoff", 0.0)))
    yoff = float(getattr(sgrid, "yoffset", getattr(sgrid, "yoff", 0.0)))

    x_edges = xoff + np.concatenate(([0.0], np.cumsum(delr)))
    y_edges = yoff + np.concatenate(([0.0], np.cumsum(delc)))
    x_cell = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_cell = 0.5 * (y_edges[:-1] + y_edges[1:])

    x_centers, y_centers = np.meshgrid(x_cell, y_cell, indexing="xy")
    return x_centers, y_centers


def _stress_period_bounds(
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]] | None:
    """Return (start, end) bounds for each stress period, or None."""
    if simulation_window is None:
        return None

    from hydromodpy.core.time import build_simulation_time_boundaries

    boundaries = build_simulation_time_boundaries(simulation_window)
    if len(boundaries) < 2:
        return None

    bounds = []
    for i in range(min(nper, len(boundaries) - 1)):
        bounds.append((boundaries[i], boundaries[i + 1]))
    return bounds


# ------------------------------------------------------------------
# Internal helpers - field discretization
# ------------------------------------------------------------------


def _discretize_one_field_record(
    field_rec: FieldRecord,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Discretize a single FieldRecord onto the solver grid.

    Handles xarray Datasets, file paths (NetCDF, GeoTIFF), and static fields.
    All returned arrays are in m/s.
    """
    data = field_rec.data
    unit = getattr(field_rec, "unit", "mm/day")
    unit_factor = _unit_to_m_per_s_factor(unit)

    if isinstance(data, (str, Path)):
        return _discretize_from_file(
            Path(data),
            x_centers=x_centers,
            y_centers=y_centers,
            nrow=nrow,
            ncol=ncol,
            nper=nper,
            period_bounds=period_bounds,
            unit_factor=unit_factor,
            method=method,
        )

    # xarray Dataset
    try:
        import xarray as xr

        if isinstance(data, xr.Dataset):
            return _discretize_from_xarray(
                data,
                x_centers=x_centers,
                y_centers=y_centers,
                nrow=nrow,
                ncol=ncol,
                nper=nper,
                period_bounds=period_bounds,
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


def _unit_to_m_per_s_factor(unit: str) -> float:
    """Return multiplication factor to convert from *unit* to m/s."""
    token = "".join(str(unit).strip().lower().split())
    french_aliases = {
        "mm/jour": "mm/day",
        "cm/jour": "cm/day",
        "m/jour": "m/day",
    }
    resolved_unit = french_aliases.get(token, unit)
    return factor_to_m_per_s(resolved_unit)


def _interp_2d(
    source_values: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    nrow: int,
    ncol: int,
    method: InterpolationMethod = "nearest",
) -> np.ndarray:
    """Interpolate a 2-D source array onto target cell centers.

    Delegates to the shared :mod:`spatial_interpolation` module.
    """
    from hydromodpy.solver.utils.mesh.cartesian_grid.spatial_interpolation import (
        interpolate_to_grid,
    )

    return interpolate_to_grid(
        source_values=np.asarray(source_values, dtype=float),
        source_x=source_x,
        source_y=source_y,
        target_x=target_x,
        target_y=target_y,
        nrow=nrow,
        ncol=ncol,
        method=method,
    )


def _discretize_from_xarray(
    ds: xr.Dataset,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Reproject an xarray Dataset onto solver cell centers."""
    # Identify the data variable to use.
    data_vars = list(ds.data_vars)
    if not data_vars:
        return {k: np.zeros((nrow, ncol), dtype=float) for k in range(nper)}
    var_name = data_vars[0]
    da = ds[var_name]

    # Identify spatial dimension names.
    x_dim, y_dim = _find_xy_dims(da)

    has_time = "time" in da.dims
    if not has_time:
        # Static field: apply to all periods.
        arr_2d = (
            _interp_2d(
                da.values,
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
                # No data for this period: use nearest time step.
                idx = int(np.argmin(np.abs((time_coords - t_start).total_seconds())))
                slice_2d = da.isel(time=idx).values
            else:
                slice_2d = da.isel(time=mask).mean(dim="time").values
            arr_2d = (
                _interp_2d(
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
            slice_2d = da.isel(time=kper).values
            arr_2d = (
                _interp_2d(
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


def _discretize_from_file(
    path: Path,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Load and discretize from a NetCDF or GeoTIFF file."""
    suffix = path.suffix.lower()
    if suffix in (".nc", ".nc4", ".netcdf"):
        import xarray as xr

        ds = xr.open_dataset(path)
        try:
            return _discretize_from_xarray(
                ds,
                x_centers=x_centers,
                y_centers=y_centers,
                nrow=nrow,
                ncol=ncol,
                nper=nper,
                period_bounds=period_bounds,
                unit_factor=unit_factor,
                method=method,
            )
        finally:
            ds.close()

    if suffix in (".tif", ".tiff"):
        return _discretize_geotiff(
            path,
            x_centers=x_centers,
            y_centers=y_centers,
            nrow=nrow,
            ncol=ncol,
            nper=nper,
            period_bounds=period_bounds,
            unit_factor=unit_factor,
            method=method,
        )

    logger.warning(
        "Unsupported file format '%s' for field discretization; returning zeros.", suffix
    )
    return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}


def _discretize_geotiff(
    path: Path,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
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
            band = src.read(1).astype(float)
            arr_2d = (
                _interp_2d(band, src_x, src_y, x_centers, y_centers, nrow, ncol, method)
                * unit_factor
            )
            return {kper: arr_2d.copy() for kper in range(nper)}

        # Multi-band: one band per time step.
        band_arrays: list[np.ndarray] = []
        for b in range(1, n_bands + 1):
            band = src.read(b).astype(float)
            arr_2d = (
                _interp_2d(band, src_x, src_y, x_centers, y_centers, nrow, ncol, method)
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
                # Use nearest available band.
                results[kper] = band_arrays[-1].copy()
            else:
                results[kper] = np.mean(band_arrays[start_b:end_b], axis=0)
        return results

    # No simulation window: one band per kper.
    return {kper: band_arrays[kper].copy() for kper in range(min(nper, len(band_arrays)))}


# ------------------------------------------------------------------
# Internal helpers - spatial mean (field → homogeneous)
# ------------------------------------------------------------------


def _spatial_mean_one_field(field_rec: FieldRecord) -> pd.Series | None:
    """Compute the spatial mean of a single FieldRecord.

    Returns a pd.Series indexed by datetime (mm/day) or None.
    """
    data = field_rec.data

    if isinstance(data, (str, Path)):
        return _spatial_mean_from_file(Path(data))

    try:
        import xarray as xr

        if isinstance(data, xr.Dataset):
            return _spatial_mean_from_xarray(data)
    except ImportError:
        pass

    return None


def _spatial_mean_from_xarray(ds: xr.Dataset) -> pd.Series | None:
    """Spatial mean of an xarray Dataset → pd.Series."""
    data_vars = list(ds.data_vars)
    if not data_vars:
        return None
    da = ds[data_vars[0]]
    x_dim, y_dim = _find_xy_dims(da)

    has_time = "time" in da.dims
    if not has_time:
        mean_val = float(da.values.mean())
        return pd.Series([mean_val], index=pd.DatetimeIndex(["2000-01-01"]))

    # Average over spatial dimensions, keep time.
    spatial_dims = [d for d in da.dims if d != "time"]
    mean_ts = da.mean(dim=spatial_dims).values
    time_index = pd.DatetimeIndex(da.coords["time"].values)
    return pd.Series(mean_ts.astype(float), index=time_index)


def _spatial_mean_from_file(path: Path) -> pd.Series | None:
    """Spatial mean from a file (NetCDF or GeoTIFF)."""
    suffix = path.suffix.lower()
    if suffix in (".nc", ".nc4", ".netcdf"):
        import xarray as xr

        ds = xr.open_dataset(path)
        try:
            return _spatial_mean_from_xarray(ds)
        finally:
            ds.close()

    if suffix in (".tif", ".tiff"):
        try:
            import rasterio

            with rasterio.open(path) as src:
                band = src.read(1).astype(float)
                mean_val = float(np.nanmean(band))
                return pd.Series([mean_val], index=pd.DatetimeIndex(["2000-01-01"]))
        except ImportError:
            pass

    return None


# ------------------------------------------------------------------
# Internal helpers - point extraction
# ------------------------------------------------------------------


def _extract_located_points(load_result: LoadResult) -> list[PointRecord]:
    """Return PointRecords that have a valid location with coordinates."""
    result = []
    for rec in load_result.points:
        loc = getattr(rec, "location", None)
        if loc is not None and hasattr(loc, "x") and hasattr(loc, "y"):
            result.append(rec)
    return result


def _period_mean(series: pd.Series, t_start: pd.Timestamp, t_end: pd.Timestamp) -> float:
    """Mean value of a series within [t_start, t_end)."""
    mask = (series.index >= t_start) & (series.index < t_end)
    subset = series[mask]
    if subset.empty:
        # Fallback: nearest time step.
        diffs = np.abs((series.index - t_start).total_seconds())
        return float(series.iloc[int(np.argmin(diffs))])
    return float(subset.mean())


def _find_xy_dims(da: object) -> tuple[str, str]:
    """Identify X and Y dimension names in a DataArray."""
    dims = [str(d) for d in da.dims]
    x_candidates = ("x", "lon", "longitude", "easting", "X")
    y_candidates = ("y", "lat", "latitude", "northing", "Y")
    x_dim = next((d for d in dims if d in x_candidates), None)
    y_dim = next((d for d in dims if d in y_candidates), None)
    # Fallback: use last two spatial dims.
    spatial_dims = [d for d in dims if d != "time"]
    if x_dim is None and len(spatial_dims) >= 1:
        x_dim = spatial_dims[-1]
    if y_dim is None and len(spatial_dims) >= 2:
        y_dim = spatial_dims[-2]
    if x_dim is None or y_dim is None:
        raise ValueError(f"Cannot identify X/Y dimensions in DataArray with dims={dims}")
    return x_dim, y_dim

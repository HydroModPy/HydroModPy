"""xarray and file-based fields on cell centers, and their spatial mean.

A record whose CRS is not the CRS of the mesh is refused, because a grid is never reprojected. A
dataset or a NetCDF file is averaged in time over each period. A GeoTIFF gives one band per time
step, and a rotated GeoTIFF is refused.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.core.config_kit.types import InterpolationMethod
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.time.coverage import enforce_coverage, samples_by_period
from hydromodpy.model.forcing.sources import (
    ForcingGridError,
    crs_mismatch,
    find_xy_dims,
    interpolate_on_cells,
    interpolate_stack_on_cells,
    pick_field_variable,
    refuse_nodata_under_cells,
    unit_to_m_per_s_factor,
)

if TYPE_CHECKING:
    import xarray as xr

    from hydromodpy.mesh.planar.hydro_mesh import HydroMesh

_NETCDF_SUFFIXES = (".nc", ".nc4", ".netcdf")
_GEOTIFF_SUFFIXES = (".tif", ".tiff")
_ACCEPTED_FILES = ", ".join((*_NETCDF_SUFFIXES, *_GEOTIFF_SUFFIXES))


_DATASET = "dataset"
"""How the refusals name a gridded source held in memory."""

_FORCING = "forcing"
"""How the messages name the variable of a record that does not state one."""


def _field_values(values: object, *, source: str, where: str) -> np.ndarray:
    """Return field values as a float array, a nodata pixel NaN, or refuse an empty grid."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ForcingGridError(
            f"The gridded forcing {source} holds no pixel in {where}: its values have the "
            f"shape {arr.shape}. Give a grid whose extent holds pixels."
        )
    return arr


def _refuse_another_crs(field_rec: Any, mesh_crs: str | None, *, variable: str) -> None:
    """Refuse a grid whose CRS is not the CRS of the mesh.

    The forcing never reprojects a grid: it reads the pixels at the cell
    coordinates as they are. When the grid or the mesh declares no CRS that
    places it on the Earth, the two cannot be compared and the grid is read as
    it is, see :func:`~hydromodpy.model.forcing.sources.crs_mismatch`.
    """
    names = crs_mismatch(getattr(field_rec, "crs", None), mesh_crs)
    if names is None:
        return
    data = field_rec.data
    source = Path(data).name if isinstance(data, (str, Path)) else _DATASET
    grid_name, mesh_name = names
    raise DataContractViolation(
        f"The {variable} grid {source} is in {grid_name} and the mesh in {mesh_name}. A forcing "
        "grid is never reprojected, so each cell would read the pixels of another place. "
        f"Reproject the grid to {mesh_name}, or build the mesh in {grid_name}."
    )


def discretize_one_field_record(
    field_rec: Any,
    *,
    centers: np.ndarray,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
    mesh: HydroMesh | None = None,
    mesh_crs: str | None = None,
) -> dict[int, np.ndarray]:
    """Discretize a single FieldRecord onto the cells.

    Handles xarray Datasets, file paths (NetCDF, GeoTIFF), and static fields.
    Any other data is refused with :class:`DataContractViolation`. ``mesh`` is
    the planar mesh of the cells, read by ``"area"`` only. ``mesh_crs`` is the
    CRS of the cells: a record in another CRS is refused. All returned arrays
    are in m/s.
    """
    data = field_rec.data
    variable = str(getattr(field_rec, "variable", None) or _FORCING)
    _refuse_another_crs(field_rec, mesh_crs, variable=variable)
    unit = getattr(field_rec, "unit", "mm/day")
    unit_factor = unit_to_m_per_s_factor(unit)

    if isinstance(data, (str, Path)):
        return discretize_from_file(
            Path(data),
            centers=centers,
            nper=nper,
            period_bounds=period_bounds,
            coverage_policy=coverage_policy,
            unit_factor=unit_factor,
            method=method,
            mesh=mesh,
            variable=variable,
        )

    import xarray as xr

    if isinstance(data, xr.Dataset):
        return discretize_from_xarray(
            data,
            centers=centers,
            nper=nper,
            period_bounds=period_bounds,
            coverage_policy=coverage_policy,
            unit_factor=unit_factor,
            method=method,
            mesh=mesh,
        )

    raise DataContractViolation(
        f"A gridded forcing record holds a {type(data).__name__}. The forcing reads an "
        f"xarray Dataset or the path of a NetCDF or GeoTIFF file ({_ACCEPTED_FILES})."
    )


def discretize_from_xarray(
    ds: xr.Dataset,
    *,
    centers: np.ndarray,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
    mesh: HydroMesh | None = None,
    source: str = _DATASET,
) -> dict[int, np.ndarray]:
    """Reproject an xarray Dataset onto the cell centers, one value per cell.

    A nodata pixel is NaN, or equal to the ``nodata``, ``_FillValue`` or
    ``missing_value`` attribute of the variable. It is refused where a cell
    reads it, see :func:`refuse_nodata_under_cells`. A period mean is NaN on a
    pixel that is nodata on any of its days. Without a simulation window, each
    time step is one stress period, and a time step past the last period is
    refused.
    """
    # Identify the data variable to use.
    var_name = pick_field_variable(ds)
    if var_name is None:
        return {k: np.zeros(centers.shape[0], dtype=float) for k in range(nper)}
    da = _mask_declared_nodata(ds[var_name])

    x_dim, y_dim = find_xy_dims(da, source=source)

    has_time = "time" in da.dims
    if not has_time:
        # Static field: apply to all periods.
        source_values = _field_values(da.values, source=source, where="the static field")
        refuse_nodata_under_cells(
            source_values,
            da.coords[x_dim].values,
            da.coords[y_dim].values,
            centers,
            method,
            source=source,
            slice_labels=["the static field"],
            mesh=mesh,
        )
        on_cells = (
            interpolate_on_cells(
                source_values,
                da.coords[x_dim].values,
                da.coords[y_dim].values,
                centers,
                method,
                mesh=mesh,
            )
            * unit_factor
        )
        return {kper: on_cells.copy() for kper in range(nper)}

    # Time-varying: aggregate per stress period, then interpolate the whole
    # slice stack in one pass (shared nearest-neighbor plan across periods).
    time_coords = pd.DatetimeIndex(da.coords["time"].values)
    slices: list[np.ndarray] = []
    labels: list[str] = []

    if period_bounds is not None:
        order = np.argsort(time_coords.asi8, kind="stable")
        sorted_coords = time_coords[order]
        boundaries = [period_bounds[0][0], *(end for _, end in period_bounds)]
        periods = samples_by_period(sorted_coords, boundaries)
        enforce_coverage(
            periods,
            boundaries,
            policy=coverage_policy,
            label="The gridded forcing record",
        )
        for kper, (inside, fill) in enumerate(zip(periods.inside, periods.fill, strict=True)):
            where = f"stress period {kper}"
            if inside.size:
                selected = da.isel(time=order[inside])
                _field_values(selected.values, source=source, where=where)
                if periods.weights is None or inside.size == 1:
                    slice_2d = selected.mean(dim="time", skipna=False).values
                else:
                    slice_2d = np.average(
                        selected.values,
                        axis=selected.get_axis_num("time"),
                        weights=periods.weights[inside],
                    )
            else:
                slice_2d = _field_values(
                    da.isel(time=int(order[int(fill)])).values, source=source, where=where
                )
            slices.append(np.asarray(slice_2d, dtype=float))
            labels.append(f"stress period {kper}")
    else:
        # No simulation window: one time step per stress period.
        _refuse_unread_slices(source, len(time_coords), nper, "time steps", windowed=False)
        for kper in range(len(time_coords)):
            slice_2d = _field_values(
                da.isel(time=kper).values, source=source, where=f"stress period {kper}"
            )
            slices.append(np.asarray(slice_2d, dtype=float))
            labels.append(f"stress period {kper}")

    if not slices:
        return {}

    refuse_nodata_under_cells(
        np.stack(slices),
        da.coords[x_dim].values,
        da.coords[y_dim].values,
        centers,
        method,
        source=source,
        slice_labels=labels,
        mesh=mesh,
    )
    interpolated = interpolate_stack_on_cells(
        np.stack(slices),
        da.coords[x_dim].values,
        da.coords[y_dim].values,
        centers,
        method,
        mesh=mesh,
    )
    return {kper: interpolated[kper] * unit_factor for kper in range(len(slices))}


def discretize_from_file(
    path: Path,
    *,
    centers: np.ndarray,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
    mesh: HydroMesh | None = None,
    variable: str = _FORCING,
) -> dict[int, np.ndarray]:
    """Load and discretize from a NetCDF or GeoTIFF file, or refuse any other file.

    ``variable`` names the variable the file holds in the coverage messages.
    """
    suffix = path.suffix.lower()
    if suffix in _NETCDF_SUFFIXES:
        import xarray as xr

        ds = xr.open_dataset(path)
        try:
            return discretize_from_xarray(
                ds,
                centers=centers,
                nper=nper,
                period_bounds=period_bounds,
                coverage_policy=coverage_policy,
                unit_factor=unit_factor,
                method=method,
                mesh=mesh,
                source=path.name,
            )
        finally:
            ds.close()

    if suffix in _GEOTIFF_SUFFIXES:
        return discretize_geotiff(
            path,
            centers=centers,
            nper=nper,
            period_bounds=period_bounds,
            coverage_policy=coverage_policy,
            unit_factor=unit_factor,
            method=method,
            mesh=mesh,
            variable=variable,
        )

    raise DataContractViolation(
        f"The gridded forcing file {path.name} has the suffix {suffix!r}. The forcing reads "
        f"NetCDF or GeoTIFF files ({_ACCEPTED_FILES})."
    )


def discretize_geotiff(
    path: Path,
    *,
    centers: np.ndarray,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    unit_factor: float,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
    mesh: HydroMesh | None = None,
    variable: str = _FORCING,
) -> dict[int, np.ndarray]:
    """Read a GeoTIFF (single- or multi-band) and discretize onto the cell centers.

    Multi-band GeoTIFFs are treated as temporal: one band per time step. With
    a simulation window, each period takes the mean of the same number of
    bands, and a band count that is not a whole multiple of the periods is
    refused. Without one, each band is one period, and a band past the last
    period is refused. A rotated transform is refused. A pixel equal to the
    declared nodata becomes NaN and is refused where a cell reads it, see
    :func:`refuse_nodata_under_cells`. ``variable`` names the variable of the
    bands in the coverage messages.
    """
    import rasterio

    with rasterio.open(path) as src:
        _refuse_rotation(src, path)
        src_x, src_y = _pixel_centres(src)
        n_bands = src.count

        if n_bands == 1:
            # Static single-band TIF.
            band = _field_values(_read_band(src, 1), source=path.name, where="band 1")
            refuse_nodata_under_cells(
                band, src_x, src_y, centers, method,
                source=path.name, slice_labels=["band 1"], mesh=mesh,
            )  # fmt: skip
            on_cells = (
                interpolate_on_cells(band, src_x, src_y, centers, method, mesh=mesh) * unit_factor
            )
            return {kper: on_cells.copy() for kper in range(nper)}

        # Multi-band: one band per time step, interpolated as one stack.
        n_periods = nper if period_bounds is None else len(period_bounds)
        _refuse_unread_slices(
            path.name, n_bands, n_periods, "bands", windowed=period_bounds is not None
        )
        bands = np.stack(
            [
                _field_values(_read_band(src, b), source=path.name, where=f"band {b}")
                for b in range(1, n_bands + 1)
            ]
        )
    refuse_nodata_under_cells(
        bands, src_x, src_y, centers, method,
        source=path.name, slice_labels=[f"band {b}" for b in range(1, n_bands + 1)], mesh=mesh,
    )  # fmt: skip
    band_arrays = list(
        interpolate_stack_on_cells(bands, src_x, src_y, centers, method, mesh=mesh) * unit_factor
    )

    # Map bands to stress periods.
    if period_bounds is not None:
        # Distribute bands evenly across periods, the same number of bands each.
        results: dict[int, np.ndarray] = {}
        bands_per_period = max(1, len(band_arrays) // len(period_bounds))
        for kper in range(min(nper, len(period_bounds))):
            start_b = kper * bands_per_period
            end_b = min(start_b + bands_per_period, len(band_arrays))
            if start_b >= len(band_arrays):
                message = (
                    f"Coverage check failed for {variable}: no GeoTIFF forcing band mapped "
                    f"to stress period {kper}."
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


def _refuse_unread_slices(
    source: str, n_slices: int, n_periods: int, kind: str, *, windowed: bool
) -> None:
    """Refuse a record with slices that no stress period reads.

    Without a window, slice k is period k, so a slice past the last period is
    unread. With one, each period takes ``n_slices // n_periods`` slices, so a
    count that is not a whole multiple of the periods leaves the last ones
    unread. Too few slices is left to the coverage rule.
    """
    if n_periods <= 0 or n_slices <= n_periods:
        return
    if not windowed:
        raise DataContractViolation(
            f"The gridded forcing {source} holds {n_slices} {kind} for {n_periods} stress "
            f"period(s) and no simulation window, so each of its {kind} is one period and "
            f"the last {n_slices - n_periods} would be read by no period. Give one per "
            "period, or a simulation window."
        )
    if n_slices % n_periods:
        raise DataContractViolation(
            f"The gridded forcing {source} holds {n_slices} {kind} for {n_periods} stress "
            f"period(s). Each period takes the same number of {kind}, so the last "
            f"{n_slices % n_periods} would be read by no period. Give a whole multiple of "
            f"{n_periods} {kind}."
        )


def _refuse_rotation(src: Any, path: Path) -> None:
    """Refuse a GeoTIFF whose transform is rotated or sheared."""
    transform = src.transform
    if transform.b or transform.d:
        raise DataContractViolation(
            f"The GeoTIFF forcing {path.name} has a rotated transform {tuple(transform)[:6]}. "
            "The forcing reads the pixel centres along the x and y axes, so a rotated grid "
            "would put each value in another place. Write the grid north up, without rotation."
        )


def _pixel_centres(src: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return the x and y of the pixel centers of an open GeoTIFF, one axis each."""
    transform = src.transform
    x = np.array([transform[2] + (c + 0.5) * transform[0] for c in range(src.width)])
    y = np.array([transform[5] + (r + 0.5) * transform[4] for r in range(src.height)])
    return x, y


def _read_band(src: Any, band: int) -> np.ndarray:
    """Read one band as floats, the pixels equal to the declared nodata as NaN."""
    values = src.read(band).astype(float)
    if src.nodata is not None:
        values[values == src.nodata] = np.nan
    return values


def spatial_mean_one_field(field_rec: Any) -> pd.Series | None:
    """Compute the spatial mean of a single FieldRecord.

    Returns a pd.Series indexed by datetime (mm/day) or None.
    """
    data = field_rec.data

    if isinstance(data, (str, Path)):
        return spatial_mean_from_file(Path(data))

    import xarray as xr

    if isinstance(data, xr.Dataset):
        return spatial_mean_from_xarray(data)
    return None


_NODATA_ATTRIBUTES = ("nodata", "_FillValue", "missing_value")
"""The attributes of a dataset variable that declare its nodata value."""


def _mask_declared_nodata(da: xr.DataArray) -> xr.DataArray:
    """Return *da* with the pixels equal to a declared nodata value as NaN.

    The value is the ``nodata``, ``_FillValue`` or ``missing_value``
    attribute, one number or a list of them. A file opened by xarray has its
    fill values masked already and keeps them in the encoding, not here.
    """
    declared: list[float] = []
    for key in _NODATA_ATTRIBUTES:
        try:
            declared.extend(np.atleast_1d(np.asarray(da.attrs[key], dtype=float)).tolist())
        except (KeyError, TypeError, ValueError):
            continue  # an absent or non-numeric attribute declares nothing
    declared = [value for value in declared if np.isfinite(value)]
    if not declared:
        return da
    return da.where(~da.isin(declared))


def _valid_means(
    stack: np.ndarray,
    *,
    source: str,
    x: np.ndarray,
    y: np.ndarray,
    slice_label: Callable[[int], str],
) -> np.ndarray:
    """Mean of the valid pixels of each slice of ``(n_slices, ...)``, or refuse an empty slice.

    A pixel is valid when it is finite. A slice with no valid pixel has no mean
    and is refused, naming the source, the slice and the footprint of the pixel
    centers *x* and *y*.
    """
    flat = stack.reshape(stack.shape[0], -1)
    valid = np.isfinite(flat)
    counts = valid.sum(axis=1)
    empty = np.flatnonzero(counts == 0)
    if empty.size:
        raise DataContractViolation(
            f"The gridded forcing {source} holds no valid pixel in {slice_label(int(empty[0]))}, "
            f"on the footprint x {np.min(x):.10g} to {np.max(x):.10g} and y {np.min(y):.10g} "
            f"to {np.max(y):.10g} (pixel centres): it has no spatial mean."
        )
    return np.where(valid, flat, 0.0).sum(axis=1) / counts


def spatial_mean_from_xarray(ds: xr.Dataset, *, source: str = _DATASET) -> pd.Series | None:
    """Spatial mean of the valid pixels of an xarray Dataset, returned as pd.Series.

    A NaN pixel and a pixel equal to the ``nodata``, ``_FillValue`` or
    ``missing_value`` attribute of the variable are left out. A time step with
    no valid pixel is refused.
    """
    var_name = pick_field_variable(ds)
    if var_name is None:
        return None
    da = _mask_declared_nodata(ds[var_name])
    x_dim, y_dim = find_xy_dims(da, source=source)
    values = _field_values(da.values, source=source, where="any slice")
    extent = {"x": da.coords[x_dim].values, "y": da.coords[y_dim].values}

    if "time" not in da.dims:
        mean = _valid_means(
            values[None, ...],
            source=source,
            slice_label=lambda _: "the static field",
            **extent,
        )
        return pd.Series([float(mean[0])], index=pd.DatetimeIndex(["2000-01-01"]))

    # Average over spatial dimensions, keep time.
    time_index = pd.DatetimeIndex(da.coords["time"].values)
    means = _valid_means(
        np.moveaxis(values, da.dims.index("time"), 0),
        source=source,
        slice_label=lambda k: f"time step {k} ({time_index[k]:%Y-%m-%d})",
        **extent,
    )
    return pd.Series(means.astype(float), index=time_index)


def spatial_mean_from_file(path: Path) -> pd.Series | None:
    """Spatial mean of the valid pixels of a file (NetCDF or GeoTIFF, first band)."""
    suffix = path.suffix.lower()
    if suffix in _NETCDF_SUFFIXES:
        import xarray as xr

        ds = xr.open_dataset(path)
        try:
            return spatial_mean_from_xarray(ds, source=path.name)
        finally:
            ds.close()

    if suffix in _GEOTIFF_SUFFIXES:
        import rasterio

        with rasterio.open(path) as src:
            band = _field_values(_read_band(src, 1), source=path.name, where="band 1")
            x, y = _pixel_centres(src)
        mean = _valid_means(
            band[None, ...], source=path.name, x=x, y=y, slice_label=lambda _: "band 1"
        )
        return pd.Series([float(mean[0])], index=pd.DatetimeIndex(["2000-01-01"]))

    return None

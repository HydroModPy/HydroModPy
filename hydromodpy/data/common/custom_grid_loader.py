"""Common loaders for custom gridded data (NetCDF and GeoTIFF)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.data.common.unit_helpers import convert_array
from hydromodpy.data.contracts.spatial_field import FieldRecord

logger = get_logger(__name__)


def load_custom_nc(
    path: Path,
    *,
    variable: str,
    unit: str,
    source_unit: str | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Load a custom NetCDF file as FieldRecord(s) converted to ``unit``."""
    import xarray as xr

    ds = xr.open_dataset(path)
    data_var = _resolve_data_var(ds, variable)

    source_unit_resolved = _resolve_source_unit(
        explicit_source_unit=source_unit,
        attrs_candidates=(ds[data_var].attrs, ds.attrs),
        target_unit=unit,
    )
    ds = _convert_dataset_to_unit(
        ds,
        data_var=data_var,
        source_unit=source_unit_resolved,
        target_unit=unit,
    )

    bbox, crs = _extract_bbox_and_crs(ds, data_var=data_var)
    nodata = _extract_nodata_from_attrs(ds[data_var].attrs)
    if nodata is None:
        raise ValueError(f"Custom grid dataset {path} must declare nodata metadata.")
    ds[data_var].attrs["nodata"] = nodata

    time_dim = _find_time_dim(ds)
    if time_dim is not None and time_dim in ds.dims:
        if project_period is not None:
            ds = ds.sel(
                {
                    time_dim: slice(
                        project_period[0].isoformat(),
                        project_period[1].isoformat(),
                    )
                },
            )
        times = ds[time_dim].values
        import pandas as pd

        time_index = pd.DatetimeIndex(times)
        date_start = time_index[0].to_pydatetime()
        date_end = time_index[-1].to_pydatetime()
        frequency = pd.infer_freq(time_index)
        if len(time_index) > 1 and frequency is None:
            raise ValueError(f"Custom grid dataset {path} must declare a regular time axis.")
    else:
        date_start = None
        date_end = None
        frequency = None

    return [
        FieldRecord(
            variable=variable,
            source="custom",
            unit=unit,
            data=ds,
            bbox=bbox,
            crs=crs,
            date_start=date_start,
            date_end=date_end,
            frequency=frequency,
            source_unit=source_unit_resolved,
        )
    ]


def load_custom_tif(
    path: Path,
    *,
    variable: str,
    unit: str,
    source_unit: str | None = None,
) -> list[FieldRecord]:
    """Load a custom GeoTIFF as a static FieldRecord converted to ``unit``."""
    import rioxarray  # noqa: F401
    import xarray as xr

    da = xr.open_dataarray(path, engine="rasterio")
    source_unit_resolved = _resolve_source_unit(
        explicit_source_unit=source_unit,
        attrs_candidates=(da.attrs,),
        target_unit=unit,
    )
    da = _convert_dataarray_to_unit(
        da,
        source_unit=source_unit_resolved,
        target_unit=unit,
    )

    if da.rio.crs is None:
        raise ValueError(f"Custom GeoTIFF {path} must declare a CRS.")
    if da.rio.nodata is None:
        raise ValueError(f"Custom GeoTIFF {path} must declare a nodata value.")
    crs = str(da.rio.crs)
    bounds = da.rio.bounds()
    bbox = (bounds[0], bounds[1], bounds[2], bounds[3])
    ds = da.to_dataset(name=variable)
    ds[variable].attrs["nodata"] = da.rio.nodata

    return [
        FieldRecord(
            variable=variable,
            source="custom",
            unit=unit,
            data=ds,
            bbox=bbox,
            crs=crs,
            date_start=None,
            date_end=None,
            frequency=None,
            source_unit=source_unit_resolved,
        )
    ]


def _extract_bbox_and_crs(ds, *, data_var: str) -> tuple[tuple, str]:
    """Extract bounding box and CRS from an xarray Dataset."""
    try:
        import rioxarray  # noqa: F401

        if hasattr(ds, "rio") and ds.rio.crs is not None:
            bounds = ds.rio.bounds()
            return (bounds[0], bounds[1], bounds[2], bounds[3]), str(ds.rio.crs)
    except ImportError:
        pass

    crs = _extract_crs_from_attrs(ds, data_var)
    if crs is None:
        raise ValueError("Custom grid dataset must declare CRS metadata.")

    x_coord = _find_coord(ds, ("x", "lon", "longitude", "LAMBX", "X"))
    y_coord = _find_coord(ds, ("y", "lat", "latitude", "LAMBY", "Y"))

    if x_coord is not None and y_coord is not None:
        x_vals = ds[x_coord].values
        y_vals = ds[y_coord].values
        bbox = (
            float(x_vals.min()),
            float(y_vals.min()),
            float(x_vals.max()),
            float(y_vals.max()),
        )
        return bbox, crs

    raise ValueError("Custom grid dataset must expose x/y or lon/lat coordinates.")


def _resolve_data_var(ds, variable: str) -> str:
    """Return the xarray data variable to use for one custom grid dataset."""
    if variable in ds.data_vars:
        return variable

    data_vars = list(ds.data_vars)
    if not data_vars:
        raise ValueError(f"No data variable found in custom grid dataset for {variable!r}.")
    raise ValueError(
        f"Custom grid dataset does not contain variable {variable!r}; "
        f"available variables: {data_vars!r}."
    )


def _extract_crs_from_attrs(ds, data_var: str) -> str | None:
    candidates = (ds[data_var].attrs, ds.attrs)
    for attrs in candidates:
        if not isinstance(attrs, dict):
            continue
        for key in ("crs", "crs_wkt", "spatial_ref"):
            raw_value = attrs.get(key)
            if raw_value is not None and str(raw_value).strip():
                return str(raw_value).strip()
    grid_mapping = ds[data_var].attrs.get("grid_mapping")
    if grid_mapping and grid_mapping in ds:
        attrs = ds[grid_mapping].attrs
        for key in ("crs_wkt", "spatial_ref", "crs"):
            raw_value = attrs.get(key)
            if raw_value is not None and str(raw_value).strip():
                return str(raw_value).strip()
        epsg = attrs.get("epsg_code")
        if epsg is not None:
            return f"EPSG:{int(epsg)}"
    return None


def _extract_nodata_from_attrs(attrs: object) -> float | int | str | None:
    if not isinstance(attrs, dict):
        return None
    for key in ("nodata", "_FillValue", "missing_value"):
        raw_value = attrs.get(key)
        if raw_value is not None and str(raw_value).strip():
            return raw_value
    return None


def _extract_unit_from_attrs(attrs: object) -> str | None:
    """Extract a declared unit from one attrs mapping when available."""
    if not isinstance(attrs, dict):
        return None

    for key in ("units", "unit"):
        raw_value = attrs.get(key)
        if raw_value is not None and str(raw_value).strip():
            return str(raw_value).strip()
    return None


def _resolve_source_unit(
    *,
    explicit_source_unit: str | None,
    attrs_candidates: tuple[object, ...],
    target_unit: str,
) -> str:
    """Resolve the source unit for one custom grid payload."""
    if explicit_source_unit is not None and str(explicit_source_unit).strip():
        return str(explicit_source_unit).strip()

    for attrs in attrs_candidates:
        declared_unit = _extract_unit_from_attrs(attrs)
        if declared_unit is not None:
            return declared_unit

    return target_unit


def _convert_dataset_to_unit(
    ds,
    *,
    data_var: str,
    source_unit: str,
    target_unit: str,
):
    """Convert one Dataset data variable from ``source_unit`` to ``target_unit``."""
    if source_unit != target_unit:
        ds = ds.copy()
        ds[data_var] = convert_array(
            ds[data_var].astype(float),
            source_unit,
            target_unit,
        )

    ds[data_var].attrs = dict(ds[data_var].attrs)
    ds[data_var].attrs["units"] = target_unit
    ds[data_var].attrs["source_unit"] = source_unit
    return ds


def _convert_dataarray_to_unit(
    da,
    *,
    source_unit: str,
    target_unit: str,
):
    """Convert one DataArray from ``source_unit`` to ``target_unit``."""
    if source_unit != target_unit:
        da = convert_array(da.astype(float), source_unit, target_unit)

    da.attrs = dict(da.attrs)
    da.attrs["units"] = target_unit
    da.attrs["source_unit"] = source_unit
    return da


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
    for dim in ds.dims:
        if hasattr(ds[dim], "dtype") and "datetime" in str(ds[dim].dtype):
            return dim
    return None

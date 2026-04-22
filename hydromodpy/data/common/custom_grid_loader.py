"""Common loaders for custom gridded data (NetCDF and GeoTIFF)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hydromodpy.data.common.unit_helpers import convert_array
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.core.logging import get_logger

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

    bbox, crs = _extract_bbox_and_crs(ds)

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

        date_start = pd.Timestamp(times[0]).to_pydatetime()
        date_end = pd.Timestamp(times[-1]).to_pydatetime()
        frequency = "D"
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

    crs = str(da.rio.crs) if da.rio.crs is not None else "EPSG:4326"
    bounds = da.rio.bounds()
    bbox = (bounds[0], bounds[1], bounds[2], bounds[3])
    ds = da.to_dataset(name=variable)

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


def _extract_bbox_and_crs(ds) -> tuple[tuple, str]:
    """Extract bounding box and CRS from an xarray Dataset."""
    crs = "EPSG:4326"

    try:
        import rioxarray  # noqa: F401

        if hasattr(ds, "rio") and ds.rio.crs is not None:
            crs = str(ds.rio.crs)
            bounds = ds.rio.bounds()
            return (bounds[0], bounds[1], bounds[2], bounds[3]), crs
    except ImportError:
        pass

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
        if abs(x_vals.max()) <= 180 and abs(y_vals.max()) <= 90:
            crs = "EPSG:4326"
        return bbox, crs

    return (0.0, 0.0, 0.0, 0.0), crs


def _resolve_data_var(ds, variable: str) -> str:
    """Return the xarray data variable to use for one custom grid dataset."""
    if variable in ds.data_vars:
        return variable

    data_vars = list(ds.data_vars)
    if not data_vars:
        raise ValueError(f"No data variable found in custom grid dataset for {variable!r}.")

    selected = data_vars[0]
    if len(data_vars) > 1:
        logger.debug(
            "Custom grid dataset for %s contains multiple variables; using %s.",
            variable,
            selected,
        )
    return selected


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

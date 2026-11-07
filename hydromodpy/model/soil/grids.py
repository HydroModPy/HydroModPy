"""The precipitation and ETP grids the soil reads, and the guards they must pass.

Never touches ``FieldRecord.dataset``, which caches the opened xarray dataset on
the shared record: a path is opened here, once, into a private ``xr.Dataset``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import CRS

from hydromodpy.core.exceptions import DataContractViolation, MissingForcingError
from hydromodpy.model.contracts import FieldRecordProto, LoadResultProto

if TYPE_CHECKING:
    from hydromodpy.core.time.window import ResolvedSimulationTimeWindow


# ---------------------------------------------------------------------------
# Forcing grids: reading, pairing, and the X1-X12E guards of spec section 4.3
# ---------------------------------------------------------------------------


def window_days(window: ResolvedSimulationTimeWindow) -> np.ndarray:
    """Every day of the run, ``[t0, tN)``: the window is an inclusive [start, end]."""
    return pd.date_range(window.start.normalize(), window.end.normalize(), freq="D").values


def _open_field_dataset(record: FieldRecordProto) -> xr.Dataset:
    """Open ``record.data`` without caching it on the shared record."""
    data = record.data
    if isinstance(data, (str, Path)):
        return xr.open_dataset(str(data))
    return data


def _variable_array(ds: xr.Dataset, record: FieldRecordProto, *, section: str) -> xr.DataArray:
    name = record.metadata.get("array_name", record.variable)
    if name in ds.data_vars:
        return ds[name]
    data_vars = list(ds.data_vars)
    if len(data_vars) == 1:
        return ds[data_vars[0]]
    raise DataContractViolation(
        f"{section} file holds no variable named {name!r} (it holds {data_vars}): "
        f"name the grid {name!r}."
    )


def _guard_dims(da: xr.DataArray, *, section: str) -> xr.DataArray:
    if set(da.dims) != {"time", "y", "x"}:
        raise DataContractViolation(
            f"{section} grid has dimensions {da.dims}, and the soil reservoir reads "
            "(time, y, x) in the CRS of the model: rename the dimensions of the file."
        )
    return da.transpose("time", "y", "x")


def _guard_calendar(da: xr.DataArray, *, section: str) -> None:
    values = da["time"].values
    if np.issubdtype(values.dtype, np.datetime64):
        return
    calendar = getattr(values[0], "calendar", type(values[0]).__name__)
    raise DataContractViolation(
        f"{section} uses the {calendar!r} calendar, and the soil reservoir needs "
        "real dates: convert the file to the standard calendar first."
    )


def _guard_crs(record: FieldRecordProto, *, section: str, model_crs: str) -> None:
    if CRS.from_user_input(record.crs) == CRS.from_user_input(model_crs):
        return
    raise DataContractViolation(
        f"{section} is in {record.crs} and the model in {model_crs}: forcing grids "
        "are never reprojected, so the soil columns would land on the wrong cells. "
        f'Reproject the file to {model_crs}, or set [geographic] crs_project = "{record.crs}".'
    )


def _guard_daily_step(da: xr.DataArray, *, section: str) -> None:
    times = pd.DatetimeIndex(da["time"].values)
    if times.size < 2:
        return
    diffs = np.diff(times.values)
    one_day = np.timedelta64(1, "D")
    if np.all(diffs == one_day):
        return
    bad_step = next(d for d in diffs if d != one_day)
    step_days = bad_step / one_day
    raise DataContractViolation(
        f"{section} holds one value every {step_days:g} days, and the soil "
        "reservoir fills and empties day by day: give it daily values (SIM2 is daily)."
    )


def _select_window(
    da: xr.DataArray,
    record: FieldRecordProto,
    *,
    section: str,
    window: ResolvedSimulationTimeWindow,
    days: np.ndarray,
) -> tuple[xr.DataArray, pd.DatetimeIndex]:
    times = pd.DatetimeIndex(da["time"].values)
    mask = (times >= window.start) & (times <= window.end)
    if int(mask.sum()) < len(days):
        first = record.date_start if record.date_start is not None else times.min()
        last = record.date_end if record.date_end is not None else times.max()
        raise DataContractViolation(
            f"{section} covers {pd.Timestamp(first):%Y-%m-%d} to "
            f"{pd.Timestamp(last):%Y-%m-%d}, and the run needs every day from "
            f"{pd.Timestamp(days[0]):%Y-%m-%d} to {pd.Timestamp(days[-1]):%Y-%m-%d}: "
            "extend the source period, or narrow [simulation.time]."
        )
    selected = da.isel(time=mask)
    return selected, times[mask]


def _guard_no_gaps(
    values: np.ndarray,
    selected_time: pd.DatetimeIndex,
    x: np.ndarray,
    y: np.ndarray,
    *,
    section: str,
) -> None:
    missing = np.isnan(values)
    if not missing.any():
        return
    it, iy, ix = np.argwhere(missing)[0]
    raise DataContractViolation(
        f"{section} has {int(missing.sum())} missing values between "
        f"{selected_time[0]:%Y-%m-%d} and {selected_time[-1]:%Y-%m-%d}, the first on "
        f"{selected_time[it]:%Y-%m-%d} in the cell at x = {x[ix]:.0f}, y = {y[iy]:.0f}: "
        "the soil reservoir needs a value for every day and cell. Fill the gaps, or "
        "narrow [simulation.time] to the covered days."
    )


def _guard_no_negative(
    values: np.ndarray, selected_time: pd.DatetimeIndex, *, section: str, family: str
) -> None:
    negative = values < 0
    if not negative.any():
        return
    it, iy, ix = np.argwhere(negative)[0]
    raise DataContractViolation(
        f"{section} has {int(negative.sum())} negative values, the first "
        f"{values[it, iy, ix]:g} mm/day on {selected_time[it]:%Y-%m-%d}: {family} "
        "cannot be negative. Check the file and its unit."
    )


def _guard_precipitation_scale(
    values: np.ndarray, selected_time: pd.DatetimeIndex, *, days: np.ndarray
) -> None:
    peak = float(np.nanmax(values))
    if len(days) >= 365 and peak < 0.5:
        raise DataContractViolation(
            f"[data.precipitation] never exceeds {peak:g} mm/day over {len(days)} "
            "days, far below any French climate: the file probably holds m/day or "
            "kg m-2 s-1 without saying so. Convert it to mm/day, or declare its unit."
        )
    if peak > 1000:
        it = int(np.unravel_index(np.nanargmax(values), values.shape)[0])
        raise DataContractViolation(
            f"[data.precipitation] reaches {peak:g} mm/day on "
            f"{selected_time[it]:%Y-%m-%d}, beyond any daily rainfall: check the unit "
            "of the file and convert it to mm/day."
        )


def _guard_etp_scale(values: np.ndarray, selected_time: pd.DatetimeIndex) -> None:
    peak = float(np.nanmax(values))
    if peak > 30:
        it = int(np.unravel_index(np.nanargmax(values), values.shape)[0])
        raise DataContractViolation(
            f"[data.etp] reaches {peak:g} mm/day on {selected_time[it]:%Y-%m-%d}, "
            "beyond any reference evapotranspiration: check the unit of the file and "
            "convert it to mm/day."
        )


def load_forcing_grid(
    result: LoadResultProto | None,
    *,
    section: str,
    family: str,
    window: ResolvedSimulationTimeWindow,
    days: np.ndarray,
    model_crs: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DatetimeIndex, FieldRecordProto]:
    """Read, guard and reshape one forcing family into a ``(T, N)`` grid."""
    if result is None or not (result.has_points or result.has_fields):
        raise MissingForcingError(
            f"{section} loaded nothing for {pd.Timestamp(days[0]):%Y-%m-%d} to "
            f"{pd.Timestamp(days[-1]):%Y-%m-%d}, and the soil reservoir needs a "
            f"value for every day: see the error logged above for the cause, or run "
            f"hmp data get {family} on the same extent to test the source alone."
        )
    if not result.has_fields:
        raise DataContractViolation(
            f"{section} holds station series, and the soil reservoir reads a daily "
            'grid: use a gridded source such as source = "sim2", or a NetCDF grid '
            'with source = "custom".'
        )
    if len(result.fields) != 1:
        raise DataContractViolation(
            f"{section} holds {len(result.fields)} grids, and the soil reservoir "
            f"reads one: keep a single [[data.{family}.sources]] block."
        )

    record = result.fields[0]
    ds = _open_field_dataset(record)
    da = _variable_array(ds, record, section=section)
    da = _guard_dims(da, section=section)
    _guard_calendar(da, section=section)
    _guard_crs(record, section=section, model_crs=model_crs)
    _guard_daily_step(da, section=section)
    selected, selected_time = _select_window(da, record, section=section, window=window, days=days)

    x = selected["x"].values
    y = selected["y"].values
    values = np.asarray(selected.values, dtype=np.float64)
    _guard_no_gaps(values, selected_time, x, y, section=section)
    _guard_no_negative(values, selected_time, section=section, family=family)
    if family == "precipitation":
        _guard_precipitation_scale(values, selected_time, days=days)
    else:
        _guard_etp_scale(values, selected_time)

    grid = values.reshape(len(selected_time), x.size * y.size)
    return grid, x, y, selected_time, record


def guard_paired_grids(
    x_p: np.ndarray,
    y_p: np.ndarray,
    time_p: pd.DatetimeIndex,
    x_e: np.ndarray,
    y_e: np.ndarray,
    time_e: pd.DatetimeIndex,
) -> None:
    same_grid = np.array_equal(x_p, x_e) and np.array_equal(y_p, y_e)
    same_days = np.array_equal(time_p.values, time_e.values)
    if same_grid and same_days:
        return
    raise DataContractViolation(
        "[data.precipitation] and [data.etp] come on two grids "
        f"({x_p.size * y_p.size} and {x_e.size * y_e.size} cells, or as many cells "
        "at other places): the soil reservoir pairs them cell by cell. Load both "
        "from the same provider, or regrid one file onto the other."
    )


def grid_field_record(
    variable: str,
    values_tn: np.ndarray,
    *,
    x: np.ndarray,
    y: np.ndarray,
    days: np.ndarray,
    like: FieldRecordProto,
) -> FieldRecordProto:
    """A record of ``variable`` on the same grid, bbox and CRS as ``like``, of its class.

    ``replace`` builds the new record from ``like`` so this layer never imports
    ``data``; every field but ``bbox`` and ``crs`` is set here.
    """
    grid = values_tn.reshape(len(days), y.size, x.size)
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), grid)},
        coords={"time": days, "y": y, "x": x},
    )
    return replace(
        like,
        variable=variable,
        source="soil_reservoir",
        unit="mm/day",
        data=dataset,
        date_start=pd.Timestamp(days[0]),
        date_end=pd.Timestamp(days[-1]),
        frequency="D",
        source_unit=None,
        metadata={"array_name": variable},
    )

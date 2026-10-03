"""Soil reservoir orchestrator: forcings in, MODFLOW-ready grids out.

Turns the daily precipitation and ETP grids ``[data.precipitation]`` and
``[data.etp]`` load into the kernel's ``SoilParameters`` and ``SoilState``,
runs the reservoir day by day, and hands back a recharge, a residual-ETP and
a runoff ``FieldRecord``, plus the printed water-budget block (spec
section 5). Never touches ``FieldRecord.dataset``, which caches the opened
xarray dataset on the shared record: a path is opened here, once, into a
private ``xr.Dataset``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import CRS, Transformer

from hydromodpy.core.exceptions import ConfigError, DataContractViolation, MissingForcingError
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.contracts import LoadResultProto
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilFluxes,
    SoilParameters,
    annual_budget,
    full_soil,
    run_soil_balance,
    spinup_state,
)

if TYPE_CHECKING:
    from hydromodpy.core.time.window import ResolvedSimulationTimeWindow

RU_LADDER_MM: tuple[float, ...] = (50.0, 100.0, 150.0, 200.0, 250.0)
RU_CLASSES_PER_CELL: int = 10


def soil_parameters(config: SoilReservoirConfig, ru_mm: np.ndarray) -> SoilParameters:
    """Kernel parameters for columns of capacity ``ru_mm``."""
    return SoilParameters(
        ru_mm=np.asarray(ru_mm, dtype=np.float64),
        alpha=config.alpha,
        kc=config.kc,
        impervious_fraction=config.impervious_fraction,
        bypass_fraction=config.bypass_fraction,
        transit_time_days=config.transit_time,
        curve_number=config.curve_number,
        runoff_time_days=config.runoff_time,
        runoff_lag_days=config.runoff_lag,
    )


@dataclass(frozen=True)
class SoilColumns:
    """Where each soil column sits and what it holds."""

    cell_index: np.ndarray  # (N,) int, flat (y, x) index of its SAFRAN cell
    class_index: np.ndarray  # (N,) int, capacity class inside the cell, 0 without raster
    x: np.ndarray  # (N,) cell centre, CRS of the run
    y: np.ndarray  # (N,)
    ru_shape: np.ndarray  # (N,) class capacity / mean capacity, 1.0 without raster
    cell_fraction: np.ndarray  # (N,) share of its cell the column covers, sums to 1 per cell
    basin_weight: np.ndarray  # (N,) cell_fraction / number of cells, sums to 1
    raster_mean_mm: float | None = None  # basin mean of [data.soil_capacity], None without raster


@dataclass(frozen=True)
class SoilForcings:
    """What the soil reservoir hands to the model, and what it computed."""

    recharge: LoadResult  # one FieldRecord "recharge", mm/day, P grid
    residual_etp: LoadResult  # one FieldRecord "etp", mm/day, P grid
    runoff: LoadResult  # one FieldRecord "runoff", mm/day, P grid, zeros without sealed area
    days: np.ndarray  # (T,) datetime64[ns], the run days [t0, tN)
    precipitation: np.ndarray  # (T, N) mm/day fed to the kernel
    etp: np.ndarray  # (T, N) mm/day as loaded
    fluxes: SoilFluxes
    columns: SoilColumns
    config: SoilReservoirConfig
    parameters: SoilParameters
    spinup_cycles: int  # 0 with spinup = "none"
    never_full_columns: int  # 0 with spinup = "none"
    crs: str

    @property
    def years(self) -> np.ndarray:
        """Calendar year of each day, shape (T,)."""
        return self.days.astype("datetime64[Y]").astype(int) + 1970


# ---------------------------------------------------------------------------
# Forcing grids: reading, pairing, and the X1-X12E guards of spec section 4.3
# ---------------------------------------------------------------------------


def _window_days(window: ResolvedSimulationTimeWindow) -> np.ndarray:
    """Every day of the run, ``[t0, tN)``: the window is an inclusive [start, end]."""
    return pd.date_range(window.start.normalize(), window.end.normalize(), freq="D").values


def _open_field_dataset(record: FieldRecord) -> xr.Dataset:
    """Open ``record.data`` without caching it on the shared record."""
    data = record.data
    if isinstance(data, (str, Path)):
        return xr.open_dataset(str(data))
    return data


def _variable_array(ds: xr.Dataset, record: FieldRecord, *, section: str) -> xr.DataArray:
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


def _guard_crs(record: FieldRecord, *, section: str, model_crs: str) -> None:
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
    record: FieldRecord,
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


def _load_forcing_grid(
    result: LoadResultProto | None,
    *,
    section: str,
    family: str,
    window: ResolvedSimulationTimeWindow,
    days: np.ndarray,
    model_crs: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DatetimeIndex, FieldRecord]:
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


def _guard_paired_grids(
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


def _grid_field_record(
    variable: str,
    values_tn: np.ndarray,
    *,
    x: np.ndarray,
    y: np.ndarray,
    days: np.ndarray,
    like: FieldRecord,
) -> FieldRecord:
    """A ``FieldRecord`` of ``variable`` on the same grid, bbox and CRS as ``like``."""
    grid = values_tn.reshape(len(days), y.size, x.size)
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), grid)},
        coords={"time": days, "y": y, "x": x},
    )
    return FieldRecord(
        variable=variable,
        source="soil_reservoir",
        unit="mm/day",
        data=dataset,
        bbox=like.bbox,
        crs=like.crs,
        date_start=pd.Timestamp(days[0]),
        date_end=pd.Timestamp(days[-1]),
        frequency="D",
        metadata={"array_name": variable},
    )


# ---------------------------------------------------------------------------
# RU raster: capacity classes inside each SAFRAN cell (spec section 1.7)
# ---------------------------------------------------------------------------


def _read_raster_pixels(
    record: FieldRecord, *, model_crs: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Valid pixel centres, reprojected to ``model_crs``, and their values."""
    import rasterio
    from rasterio.transform import xy as pixel_xy

    with rasterio.open(str(record.data)) as src:
        band = src.read(1, masked=True)
        rows, cols = np.where(~np.ma.getmaskarray(band))
        values = np.asarray(band)[rows, cols].astype(np.float64)
        raw_x, raw_y = pixel_xy(src.transform, rows, cols)
    px = np.asarray(raw_x, dtype=np.float64)
    py = np.asarray(raw_y, dtype=np.float64)
    if CRS.from_user_input(record.crs) != CRS.from_user_input(model_crs):
        transformer = Transformer.from_crs(record.crs, model_crs, always_xy=True)
        px, py = (np.asarray(v, dtype=np.float64) for v in transformer.transform(px, py))
    return px, py, values


def _grid_steps(
    x: np.ndarray, y: np.ndarray, bbox: tuple[float, float, float, float]
) -> tuple[float, float]:
    """(dx, dy) of the P grid: the other axis' step when one axis has a single cell,
    or the bbox span on both axes for a 1x1 grid."""
    dx = float(abs(x[1] - x[0])) if x.size > 1 else None
    dy = float(abs(y[1] - y[0])) if y.size > 1 else None
    if dx is None and dy is None:
        return float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])
    if dx is None:
        return dy, dy
    if dy is None:
        return dx, dx
    return dx, dy


def capacity_classes(
    soil_capacity: LoadResultProto,
    *,
    x: np.ndarray,
    y: np.ndarray,
    crs: str,
    bbox: tuple[float, float, float, float],
    n_classes: int = RU_CLASSES_PER_CELL,
) -> SoilColumns:
    """Spread each SAFRAN cell into capacity classes from a soil capacity raster."""
    record = soil_capacity.fields[0]
    px, py, values = _read_raster_pixels(record, model_crs=crs)

    ny, nx = y.size, x.size
    n_cells = ny * nx
    dx, dy = _grid_steps(x, y, bbox)
    ix = np.argmin(np.abs(px[:, None] - x[None, :]), axis=1)
    iy = np.argmin(np.abs(py[:, None] - y[None, :]), axis=1)
    inside = (np.abs(px - x[ix]) <= dx / 2) & (np.abs(py - y[iy]) <= dy / 2)

    inside_values = values[inside]
    negative = inside_values < 0
    if negative.any():
        raise DataContractViolation(
            "[data.soil_capacity] holds negative values (down to "
            f"{float(inside_values[negative].min()):g} mm): a soil water capacity "
            "is 0 mm or more. Check the raster and its nodata value."
        )

    cell_of_pixel = np.where(inside, iy * nx + ix, -1)
    order = np.argsort(cell_of_pixel, kind="stable")
    sorted_cells = cell_of_pixel[order]
    sorted_values = values[order]
    boundaries = np.searchsorted(sorted_cells, np.arange(n_cells + 1))

    cell_index: list[int] = []
    class_index: list[int] = []
    col_x: list[float] = []
    col_y: list[float] = []
    cell_fraction: list[float] = []
    class_mean: list[float] = []
    for c in range(n_cells):
        pixels = sorted_values[boundaries[c] : boundaries[c + 1]]
        iy_c, ix_c = divmod(c, nx)
        if pixels.size == 0:
            raise DataContractViolation(
                "[data.soil_capacity] covers no part of the SAFRAN cell centred on "
                f"x = {x[ix_c]:.0f}, y = {y[iy_c]:.0f}: every cell of the forcing "
                "grid needs soil capacity values. Extend the raster, or narrow the "
                "forcing extent."
            )
        groups = [group for group in np.array_split(np.sort(pixels), n_classes) if group.size > 0]
        for j, group in enumerate(groups):
            cell_index.append(c)
            class_index.append(j)
            col_x.append(float(x[ix_c]))
            col_y.append(float(y[iy_c]))
            cell_fraction.append(group.size / pixels.size)
            class_mean.append(float(group.mean()))

    cell_index_arr = np.asarray(cell_index, dtype=np.int64)
    cell_fraction_arr = np.asarray(cell_fraction, dtype=np.float64)
    class_mean_arr = np.asarray(class_mean, dtype=np.float64)
    basin_weight_arr = cell_fraction_arr / n_cells
    raster_mean = float(np.sum(basin_weight_arr * class_mean_arr))
    if raster_mean == 0.0:
        raise DataContractViolation(
            "[data.soil_capacity] is 0 mm over every SAFRAN cell, so it gives no "
            "shape to spread ru over: check the raster, or remove [data.soil_capacity] "
            "to use a uniform ru."
        )

    return SoilColumns(
        cell_index=cell_index_arr,
        class_index=np.asarray(class_index, dtype=np.int64),
        x=np.asarray(col_x, dtype=np.float64),
        y=np.asarray(col_y, dtype=np.float64),
        ru_shape=class_mean_arr / raster_mean,
        cell_fraction=cell_fraction_arr,
        basin_weight=basin_weight_arr,
        raster_mean_mm=raster_mean,
    )


def _aggregate_to_cells(values_tn: np.ndarray, columns: SoilColumns, n_cells: int) -> np.ndarray:
    """Weighted sum of columns back onto their SAFRAN cells, shape ``(T, n_cells)``.

    One ``FieldRecord`` per quantity (spec section 7): several classes of the
    same cell are summed here, weighted by ``cell_fraction``, never averaged
    twice by the discretizer.
    """
    weighted = (values_tn * columns.cell_fraction).T
    out = np.zeros((n_cells, values_tn.shape[0]), dtype=np.float64)
    np.add.at(out, columns.cell_index, weighted)
    return out.T


# ---------------------------------------------------------------------------
# Spin-up shared by the run and the RU ladder
# ---------------------------------------------------------------------------


def _spinup_or_full(
    config: SoilReservoirConfig, params: SoilParameters, precipitation: np.ndarray, etp: np.ndarray
):
    """Starting state under ``config.spinup``, and the ``Spinup`` that produced it.

    Returns ``(state, None)`` for ``spinup = "none"``: nothing settles, so
    there is nothing to check.
    """
    if config.spinup == "none":
        return full_soil(params), None
    result = spinup_state(precipitation[:365], etp[:365], params)
    return result.state, result


def _runoff_cn_history(spinup_result) -> np.ndarray | None:
    """Days preceding day 0 for ``runoff_lag``: the settled spin-up's last cycle, or None.

    A settled first year repeats forever by construction, so its own days are
    the best estimate of what came before the run; ``spinup = "none"`` or
    ``runoff_lag = 0`` (which never reads this) leaves the first days at zero.
    """
    return spinup_result.last_cycle_runoff_cn if spinup_result is not None else None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def compute_soil_forcings(
    *,
    precipitation: LoadResultProto | None,
    etp: LoadResultProto | None,
    config: SoilReservoirConfig,
    window: ResolvedSimulationTimeWindow,
    model_crs: str,
    soil_capacity: LoadResultProto | None = None,
) -> SoilForcings:
    """Run the soil reservoir over ``[simulation.time]`` and grid its outputs back."""
    days = _window_days(window)
    precip_grid, x_p, y_p, time_p, precip_record = _load_forcing_grid(
        precipitation,
        section="[data.precipitation]",
        family="precipitation",
        window=window,
        days=days,
        model_crs=model_crs,
    )
    etp_grid, x_e, y_e, time_e, _etp_record = _load_forcing_grid(
        etp,
        section="[data.etp]",
        family="etp",
        window=window,
        days=days,
        model_crs=model_crs,
    )
    _guard_paired_grids(x_p, y_p, time_p, x_e, y_e, time_e)

    ny, nx = y_p.size, x_p.size
    n_cells = ny * nx
    if soil_capacity is None:
        columns = SoilColumns(
            cell_index=np.arange(n_cells),
            class_index=np.zeros(n_cells, dtype=np.int64),
            x=np.tile(x_p, ny),
            y=np.repeat(y_p, nx),
            ru_shape=np.ones(n_cells),
            cell_fraction=np.ones(n_cells),
            basin_weight=np.full(n_cells, 1.0 / n_cells),
        )
    else:
        columns = capacity_classes(
            soil_capacity, x=x_p, y=y_p, crs=model_crs, bbox=precip_record.bbox
        )

    precip_columns = precip_grid[:, columns.cell_index]
    etp_columns = etp_grid[:, columns.cell_index]

    ru_mm = config.ru * columns.ru_shape
    parameters = soil_parameters(config, ru_mm)
    initial, spinup_result = _spinup_or_full(config, parameters, precip_columns, etp_columns)
    if spinup_result is not None and not spinup_result.settled:
        first_year = (
            f"{pd.Timestamp(days[0]):%Y-%m-%d} to "
            f"{pd.Timestamp(days[0]) + pd.Timedelta(days=364):%Y-%m-%d}"
        )
        raise ConfigError(
            "the soil storage at the end of the first year still moved by "
            f"{spinup_result.last_change_mm:.2f} mm after 20 repetitions of "
            f"{first_year}: the first year does not bring the soil to a repeating "
            'state. Write spinup = "none" under [flow.sinks_sources.recharge.soil], '
            "or start the run on a year that refills the soil."
        )
    spinup_cycles = spinup_result.cycles if spinup_result is not None else 0
    never_full_columns = int(np.sum(spinup_result.never_full)) if spinup_result is not None else 0

    fluxes = run_soil_balance(
        precip_columns,
        etp_columns,
        parameters,
        initial,
        runoff_cn_history_mm=_runoff_cn_history(spinup_result),
    )

    recharge_grid = _aggregate_to_cells(fluxes.recharge, columns, n_cells)
    residual_etp_grid = _aggregate_to_cells(fluxes.residual_etp, columns, n_cells)
    runoff_grid = _aggregate_to_cells(fluxes.runoff, columns, n_cells)

    recharge_field = _grid_field_record(
        "recharge", recharge_grid, x=x_p, y=y_p, days=days, like=precip_record
    )
    residual_etp_field = _grid_field_record(
        "etp", residual_etp_grid, x=x_p, y=y_p, days=days, like=precip_record
    )
    runoff_field = _grid_field_record(
        "runoff", runoff_grid, x=x_p, y=y_p, days=days, like=precip_record
    )

    return SoilForcings(
        recharge=LoadResult(fields=[recharge_field]),
        residual_etp=LoadResult(fields=[residual_etp_field]),
        runoff=LoadResult(fields=[runoff_field]),
        days=days,
        precipitation=precip_columns,
        etp=etp_columns,
        fluxes=fluxes,
        columns=columns,
        config=config,
        parameters=parameters,
        spinup_cycles=spinup_cycles,
        never_full_columns=never_full_columns,
        crs=precip_record.crs,
    )


def ru_ladder(
    forcings: SoilForcings, ru_values: tuple[float, ...] = RU_LADDER_MM
) -> tuple[tuple[float, float], ...]:
    """Basin recharge, mm/year, for each ``ru`` in ``ru_values``, other parameters fixed.

    A rung whose spin-up does not settle in 20 cycles reports ``nan`` rather
    than a number built on a soil state that never repeated: this table is
    informational, so it stays silent about the run itself (X13 already
    checked that) but never prints a silently wrong figure for a rung.
    """
    n_years = len(forcings.days) / 365.25
    rows = []
    for ru in ru_values:
        ru_mm = ru * forcings.columns.ru_shape
        parameters = soil_parameters(forcings.config, ru_mm)
        initial, spinup_result = _spinup_or_full(
            forcings.config, parameters, forcings.precipitation, forcings.etp
        )
        if spinup_result is not None and not spinup_result.settled:
            rows.append((ru, float("nan")))
            continue
        fluxes = run_soil_balance(
            forcings.precipitation,
            forcings.etp,
            parameters,
            initial,
            runoff_cn_history_mm=_runoff_cn_history(spinup_result),
        )
        basin_recharge = fluxes.recharge @ forcings.columns.basin_weight
        rows.append((ru, float(basin_recharge.sum() / n_years)))
    return tuple(rows)


def gauged_discharge_line(
    hydrometry: LoadResultProto | None, *, days: np.ndarray, catchment_area_km2: float | None
) -> str:
    """The gauged-discharge line of the printed budget, or why it is not shown."""
    if hydrometry is None or not hydrometry.has_points:
        return "gauged discharge: not shown, no [data.hydrometry] loaded"
    if len(hydrometry.points) != 1:
        return (
            f"gauged discharge: not shown, {len(hydrometry.points)} stations loaded "
            "and the comparison needs the one at the outlet"
        )
    if not catchment_area_km2 or catchment_area_km2 <= 0:
        return "gauged discharge: not shown, the catchment area is unknown"

    start, end = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    station = hydrometry.points[0]
    series = station.data.set_index("datetime")["value"]
    windowed = series[(series.index >= start) & (series.index <= end)].dropna()
    if windowed.empty:
        return (
            "gauged discharge: not shown, the station has no value between "
            f"{start:%Y-%m-%d} and {end:%Y-%m-%d}"
        )

    mean_q_m3s = float(windowed.mean())
    v_mm_per_year = _no_negative_zero(
        mean_q_m3s * 86400 * 365.25 / (catchment_area_km2 * 1e6) * 1000, 1
    )
    return (
        f"gauged discharge {station.station_id}: {v_mm_per_year:.1f} mm/year on "
        f"{windowed.size} of {days.size} days, catchment {catchment_area_km2:.2f} km2"
    )


# ---------------------------------------------------------------------------
# Printed water-budget block (spec section 5.2)
# ---------------------------------------------------------------------------


def _no_negative_zero(value: float, decimals: int) -> float:
    """Round to ``decimals`` places without ever landing on a printed ``-0.0``.

    A sum that is really zero can carry a tiny negative float error; rounded
    and printed as is, it would read as a small deficit instead of closing.
    """
    return round(value, decimals) + 0.0


def _header_line(days: np.ndarray, n_cells: int, n_classes: int, *, has_raster: bool) -> str:
    start, end = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    if has_raster:
        classes_phrase = f"up to {n_classes} capacity classes each"
    else:
        unit = "class" if n_classes == 1 else "classes"
        classes_phrase = f"{n_classes} capacity {unit} each"
    return (
        f"Soil reservoir, {start:%Y-%m-%d} to {end:%Y-%m-%d} ({len(days)} days), "
        f"{n_cells} SAFRAN cells, {classes_phrase}"
    )


def _parameters_line(config: SoilReservoirConfig, raster_mean_mm: float | None) -> str:
    ru_clause = (
        f"ru {config.ru:g} mm (raster mean {raster_mean_mm:.0f} mm rescaled)"
        if raster_mean_mm is not None
        else f"ru {config.ru:g} mm"
    )
    lag_clause = f", runoff lag {config.runoff_lag:g} days" if config.runoff_lag != 0.0 else ""
    cn_clause = (
        f", curve number {config.curve_number:g}, runoff time {config.runoff_time:g} days"
        f"{lag_clause}"
        if config.curve_number is not None
        else ""
    )
    return (
        f"{ru_clause}, alpha {config.alpha:g}, kc {config.kc:.4g}, "
        f"impervious {100 * config.impervious_fraction:.3g} %, "
        f"bypass {100 * config.bypass_fraction:.3g} %, "
        f"transit time {config.transit_time:g} days{cn_clause}"
    )


def _starting_soil_line(forcings: SoilForcings) -> str:
    config = forcings.config
    if config.spinup == "none":
        return 'starting soil: full (spinup = "none")'
    first_day = pd.Timestamp(forcings.days[0])
    label = (
        str(first_day.year) if (first_day.month, first_day.day) == (1, 1) else "the first 365 days"
    )
    line = f"starting soil: {label} repeated {forcings.spinup_cycles} times, settled within 0.1 mm"
    if forcings.never_full_columns > 0:
        n_columns = forcings.columns.cell_index.size
        line += f"; the soil never filled on {forcings.never_full_columns} of {n_columns} columns"
    return line


def _table_header(y_dry: int | None, y_wet: int | None) -> str:
    if y_dry is None:
        return f"{'mm/year':<22}{'mean':>8}"
    return (
        f"{'mm/year':<22}{'mean':>8}{str(y_dry) + ' least rain':>18}{str(y_wet) + ' most rain':>17}"
    )


def _data_row(
    label: str,
    array_yn: np.ndarray,
    weights: np.ndarray,
    scale: float,
    dry_idx: int | None,
    wet_idx: int | None,
    *,
    signed: bool = False,
) -> str:
    basin = array_yn @ weights
    mean = _no_negative_zero(basin.sum() / scale, 1)
    mean_str = f"{mean:>+8.1f}" if signed else f"{mean:>8.1f}"
    if dry_idx is None:
        return f"{label:<22}{mean_str}"
    dry = _no_negative_zero(basin[dry_idx], 1)
    wet = _no_negative_zero(basin[wet_idx], 1)
    dry_str = f"{dry:>+18.1f}" if signed else f"{dry:>18.1f}"
    wet_str = f"{wet:>+17.1f}" if signed else f"{wet:>17.1f}"
    return f"{label:<22}{mean_str}{dry_str}{wet_str}"


def _summer_line(forcings: SoilForcings) -> str | None:
    months = pd.DatetimeIndex(forcings.days).month
    summer = np.isin(months, (7, 8, 9))
    if not summer.any():
        return None
    basin_recharge = forcings.fluxes.recharge @ forcings.columns.basin_weight
    value = _no_negative_zero(float(np.mean(basin_recharge[summer])), 3)
    return f"recharge July-September: {value:.3f} mm/day"


def soil_budget_lines(
    forcings: SoilForcings,
    *,
    ladder: tuple[tuple[float, float], ...],
    gauged_line: str,
    sent_to_evt: bool,
) -> tuple[str, ...]:
    """The printed soil water-budget block of spec section 5.2, one str per line."""
    days = forcings.days
    n_days = len(days)
    n_cells = int(np.unique(forcings.columns.cell_index).size)
    n_classes = int(forcings.columns.class_index.max()) + 1
    raster_mean_mm = forcings.columns.raster_mean_mm

    annual = annual_budget(
        forcings.years,
        forcings.precipitation,
        forcings.etp,
        forcings.fluxes,
        forcings.columns.basin_weight,
    )
    full_years = annual.days >= 365
    if np.any(full_years):
        precipitation_totals = np.where(full_years, annual.basin("precipitation"), np.nan)
        dry_idx = int(np.nanargmin(precipitation_totals))
        wet_idx = int(np.nanargmax(precipitation_totals))
        y_dry, y_wet = int(annual.years[dry_idx]), int(annual.years[wet_idx])
    else:
        dry_idx = wet_idx = y_dry = y_wet = None

    scale = n_days / 365.25
    storage_change = (
        annual.soil_storage_change
        + annual.transit_storage_change
        + annual.cn_storage_change
        + annual.lag_storage_change
    )
    impervious_only = annual.runoff - annual.runoff_cn

    lines = [
        _header_line(days, n_cells, n_classes, has_raster=raster_mean_mm is not None),
        _parameters_line(forcings.config, raster_mean_mm),
        _starting_soil_line(forcings),
        _table_header(y_dry, y_wet),
        _data_row("precipitation", annual.precipitation, annual.weights, scale, dry_idx, wet_idx),
        _data_row("ETP", annual.etp, annual.weights, scale, dry_idx, wet_idx),
        _data_row("ETR", annual.etr, annual.weights, scale, dry_idx, wet_idx),
        _data_row("recharge to MODFLOW", annual.recharge, annual.weights, scale, dry_idx, wet_idx),
        _data_row("impervious runoff", impervious_only, annual.weights, scale, dry_idx, wet_idx),
    ]
    if forcings.config.curve_number is not None:
        lines.append(
            _data_row(
                "curve-number runoff", annual.runoff_cn, annual.weights, scale, dry_idx, wet_idx
            )
        )
    lines.extend(
        [
            _data_row(
                "storage change",
                storage_change,
                annual.weights,
                scale,
                dry_idx,
                wet_idx,
                signed=True,
            ),
            _data_row("closure", annual.residual, annual.weights, scale, dry_idx, wet_idx),
        ]
    )

    unmet = _no_negative_zero(float((annual.residual_etp @ annual.weights).sum() / scale), 1)
    if sent_to_evt:
        lines.append(
            f"unmet ETP {unmet:.1f} mm/year, offered to EVT: the water table gives "
            "it only where it is shallow"
        )
    else:
        lines.append(
            f'unmet ETP {unmet:.1f} mm/year, not sent to MODFLOW: add "etp" to '
            "flow.active_sinks_sources to let a shallow water table evaporate it"
        )

    summer_line = _summer_line(forcings)
    if summer_line is not None:
        lines.append(summer_line)

    ladder_text = " | ".join(f"{ru:g} mm {_no_negative_zero(v, 1):.1f}" for ru, v in ladder)
    lines.append(f"recharge for other ru, mm/year: {ladder_text}")

    lines.append(gauged_line)

    return tuple(lines)


__all__ = [
    "RU_CLASSES_PER_CELL",
    "RU_LADDER_MM",
    "SoilColumns",
    "SoilForcings",
    "capacity_classes",
    "compute_soil_forcings",
    "gauged_discharge_line",
    "ru_ladder",
    "soil_budget_lines",
    "soil_parameters",
]

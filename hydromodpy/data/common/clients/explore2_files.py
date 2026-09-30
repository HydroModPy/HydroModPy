"""DRIAS Explore2 NetCDF reader, shared by precipitation and ETP.

Reads one local Explore2-Climat file (no network): renames its variable
(``prtotAdjust`` -> ``precipitation``, ``evspsblpotAdjust`` -> ``etp``),
converts ``kg m-2 s-1`` to mm/day, cuts by the run bbox in the file's native
CRS (Lambert II extended, EPSG:27572) with a one-cell margin before any value
is read into memory, and refuses a non-standard calendar.

The native SAFRAN grid is a Cartesian grid in EPSG:27572, but reprojecting its
cell centres into the model CRS turns them into a warped, not axis-aligned,
set of points: the discretisation reads a plain regular ``(y, x)`` grid
(``spatial/mesh/cartesian_grid/_sgrid_field_grid_utils.py:119-134``), so this
module resamples the reprojected centres by nearest neighbour onto a new
regular grid of the same spacing (8 km) in the model CRS.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.common.unit_helpers import convert_array

if TYPE_CHECKING:  # pragma: no cover - typing only
    import xarray as xr

    from hydromodpy.data.contracts.spatial_field import FieldRecord

EXPLORE2_NATIVE_CRS = "EPSG:27572"
"""The CRS a DRIAS Explore2 file's x/y coordinates are written in: Lambert II extended."""

EXPLORE2_CRS = "EPSG:2154"
"""The CRS this reader resamples onto: the one every FieldRecord of this build carries."""

EXPLORE2_CELL_SIZE_M = 8000.0
"""SAFRAN grid spacing, in metres, both native and resampled."""

_SOURCE_UNIT = "kg m-2 s-1"

_VARIABLE_NAMES: dict[str, str] = {
    "precipitation": "prtotAdjust",
    "etp": "evspsblpotAdjust",
}
"""The variable this reader serves, mapped to its name in a DRIAS file."""

_REFUSED_CALENDARS = ("noleap", "360_day")

_X5 = (
    "{section} uses the {calendar!r} calendar, and the soil reservoir needs "
    "real dates: convert the file to the standard calendar first."
)

_METRE_UNIT_TOKENS = {"m", "metre", "metres", "meter", "meters"}
_HECTOMETRE_UNIT_TOKENS = {"hm", "hectometre", "hectometres", "hectometer", "hectometers"}


def read_explore2(
    path: Path,
    *,
    variable: str,
    bbox: tuple[float, float, float, float] | None,
    project_period: tuple[datetime, datetime] | None,
) -> list[FieldRecord]:
    """Read one DRIAS Explore2 file as a single FieldRecord in mm/day.

    ``variable`` is ``"precipitation"`` or ``"etp"``, the name the returned
    grid carries. ``bbox`` is the run's box in :data:`EXPLORE2_CRS`.
    """
    if bbox is None:
        raise ValueError("Explore2 source requires a bounding box (set extent or mask_path).")
    section = f"[data.{variable}]"
    source_variable = _VARIABLE_NAMES[variable]

    import xarray as xr

    from hydromodpy.data.contracts.spatial_field import FieldRecord

    ds = xr.open_dataset(path, decode_times=False)

    calendar = str(ds["time"].attrs.get("calendar", "standard"))
    if calendar.lower() in _REFUSED_CALENDARS:
        raise DataContractViolation(_X5.format(section=section, calendar=calendar))
    dates = _decode_time(ds["time"], calendar)

    x_native = ds["x"].values.astype(float) * _coord_scale_to_metres(ds["x"].attrs.get("units"))
    y_native = ds["y"].values.astype(float) * _coord_scale_to_metres(ds["y"].attrs.get("units"))

    native_bbox = _reproject_bbox(bbox, EXPLORE2_CRS, EXPLORE2_NATIVE_CRS)
    x_slice = _contiguous_index_range(
        x_native, native_bbox[0] - EXPLORE2_CELL_SIZE_M, native_bbox[2] + EXPLORE2_CELL_SIZE_M
    )
    y_slice = _contiguous_index_range(
        y_native, native_bbox[1] - EXPLORE2_CELL_SIZE_M, native_bbox[3] + EXPLORE2_CELL_SIZE_M
    )
    t_slice = _time_index_range(dates, project_period)

    # Cut before reading any value: a national file is several GB per variable.
    cropped = ds[source_variable].isel(x=x_slice, y=y_slice, time=t_slice)
    values = convert_array(_materialize(cropped), _SOURCE_UNIT, "mm/day")

    x_scatter, y_scatter = _reproject_grid(
        x_native[x_slice], y_native[y_slice], EXPLORE2_NATIVE_CRS, EXPLORE2_CRS
    )
    target_x_1d, target_y_1d = _regular_target_grid(x_scatter, y_scatter)
    resampled = _resample_nearest(values, x_scatter, y_scatter, target_x_1d, target_y_1d)

    out = xr.Dataset(
        {variable: (("time", "y", "x"), resampled)},
        coords={"time": dates[t_slice], "y": target_y_1d, "x": target_x_1d},
    )
    out[variable].attrs["units"] = "mm/day"

    record_dates = dates[t_slice]
    return [
        FieldRecord(
            variable=variable,
            source="explore2",
            unit="mm/day",
            data=out,
            bbox=(
                float(target_x_1d.min()),
                float(target_y_1d.min()),
                float(target_x_1d.max()),
                float(target_y_1d.max()),
            ),
            crs=EXPLORE2_CRS,
            date_start=_to_datetime(record_dates.min()),
            date_end=_to_datetime(record_dates.max()),
            frequency="D",
            source_unit=_SOURCE_UNIT,
        )
    ]


class Explore2Source:
    """The ``SOURCES`` entry of a variable read from a local DRIAS Explore2 file.

    Called as ``fetch(cfg, *, bbox, period, context)`` by the grid managers; it
    reads only ``cfg.path``, the file this source is served from.
    """

    def __init__(self, variable: str) -> None:
        self.variable = variable

    def variables(self, cfg: object) -> list[str]:
        """Name of the one grid this config yields."""
        del cfg
        return [self.variable]

    def __call__(
        self,
        cfg: object,
        *,
        bbox: tuple[float, float, float, float] | None,
        period: tuple[datetime, datetime] | None,
        context: object,
    ) -> list[FieldRecord]:
        del context
        return read_explore2(
            Path(cfg.path), variable=self.variable, bbox=bbox, project_period=period
        )


def explore2_source(variable: str) -> Explore2Source:
    """The ``SOURCES`` entry that reads ``variable`` from a local Explore2 file."""
    return Explore2Source(variable)


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _materialize(data_array: xr.DataArray) -> np.ndarray:
    """Read an already-cropped data array into memory."""
    return np.asarray(data_array.values, dtype=float)


def _decode_time(time_var: xr.DataArray, calendar: str) -> np.ndarray:
    from xarray.coding.times import decode_cf_datetime

    units = time_var.attrs.get("units")
    if not units:
        raise ValueError("DRIAS Explore2 file's time coordinate must declare a units attribute.")
    return decode_cf_datetime(
        time_var.values, units=str(units), calendar=calendar, use_cftime=False
    )


def _coord_scale_to_metres(units: object) -> float:
    token = str(units).strip().lower()
    if token in _METRE_UNIT_TOKENS:
        return 1.0
    if token in _HECTOMETRE_UNIT_TOKENS:
        return 100.0
    raise ValueError(
        f"DRIAS Explore2 file declares x/y units {units!r}, and only metres or "
        "hectometres are handled."
    )


def _reproject_bbox(
    bbox: tuple[float, float, float, float], src_crs: str, dst_crs: str
) -> tuple[float, float, float, float]:
    """Reproject a bbox by its four corners, since a rotation moves the diagonal."""
    xmin, ymin, xmax, ymax = bbox
    xs, ys = _reproject_grid(
        np.array([xmin, xmin, xmax, xmax]), np.array([ymin, ymax, ymin, ymax]), src_crs, dst_crs
    )
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def _reproject_grid(
    x: np.ndarray, y: np.ndarray, src_crs: str, dst_crs: str
) -> tuple[np.ndarray, np.ndarray]:
    """Reproject cell-centre coordinates. 1-D inputs broadcast to a 2-D (y, x) grid."""
    from pyproj import Transformer

    if x.ndim == 1 and y.ndim == 1:
        x, y = np.meshgrid(x, y, indexing="xy")
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    xt, yt = transformer.transform(x, y)
    return np.asarray(xt, dtype=float), np.asarray(yt, dtype=float)


def _contiguous_index_range(coord_m: np.ndarray, lo: float, hi: float) -> slice:
    """The contiguous position range where a monotonic coordinate falls in [lo, hi]."""
    inside = np.flatnonzero((coord_m >= lo) & (coord_m <= hi))
    if inside.size == 0:
        raise ValueError(
            f"DRIAS Explore2 file covers no cell between {lo:.0f} and {hi:.0f} on this axis."
        )
    return slice(int(inside.min()), int(inside.max()) + 1)


def _time_index_range(dates: np.ndarray, project_period: tuple[datetime, datetime] | None) -> slice:
    if project_period is None:
        return slice(None)
    start, end = project_period
    inside = np.flatnonzero((dates >= np.datetime64(start)) & (dates <= np.datetime64(end)))
    if inside.size == 0:
        raise ValueError(
            f"DRIAS Explore2 file holds no day between {start:%Y-%m-%d} and {end:%Y-%m-%d}."
        )
    return slice(int(inside.min()), int(inside.max()) + 1)


def _regular_target_grid(
    x_scatter: np.ndarray, y_scatter: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """A regular 8 km grid in the model CRS, covering the reprojected centres."""
    cell = EXPLORE2_CELL_SIZE_M
    x0 = math.floor(x_scatter.min() / cell) * cell
    x1 = math.ceil(x_scatter.max() / cell) * cell
    y0 = math.floor(y_scatter.min() / cell) * cell
    y1 = math.ceil(y_scatter.max() / cell) * cell
    return np.arange(x0, x1 + cell, cell), np.arange(y0, y1 + cell, cell)


def _resample_nearest(
    values: np.ndarray,
    x_scatter: np.ndarray,
    y_scatter: np.ndarray,
    target_x_1d: np.ndarray,
    target_y_1d: np.ndarray,
) -> np.ndarray:
    from hydromodpy.spatial.mesh.cartesian_grid.spatial_interpolation import (
        interpolate_stack_to_grid,
    )

    target_x, target_y = np.meshgrid(target_x_1d, target_y_1d, indexing="xy")
    return interpolate_stack_to_grid(
        values,
        x_scatter,
        y_scatter,
        target_x,
        target_y,
        target_y_1d.size,
        target_x_1d.size,
        method="nearest",
    )


def _to_datetime(value: np.datetime64) -> datetime:
    import pandas as pd

    return pd.Timestamp(value).to_pydatetime()


__all__ = [
    "EXPLORE2_CELL_SIZE_M",
    "EXPLORE2_CRS",
    "EXPLORE2_NATIVE_CRS",
    "Explore2Source",
    "explore2_source",
    "read_explore2",
]

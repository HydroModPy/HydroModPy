"""Shared builders for sgrid field-discretization unit tests."""

from __future__ import annotations

import types
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import xarray as xr

from hydromodpy.core.time import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.spatial_field import FieldRecord

MM_DAY_TO_M_S = 1.0e-3 / 86400.0


def _make_sgrid(nrow: int, ncol: int, dx: float = 10.0, dy: float = 10.0):
    """Minimal mock structured grid with cell-center arrays."""
    x_centers = np.array([[(j + 0.5) * dx for j in range(ncol)] for _ in range(nrow)])
    y_centers = np.array([[(i + 0.5) * dy for i in range(nrow)] for _ in range(nrow)])
    # Fix y_centers: each row should have a constant y
    y_centers = np.array([[(nrow - i - 0.5) * dy] * ncol for i in range(nrow)])
    return types.SimpleNamespace(
        nrow=nrow,
        ncol=ncol,
        xcellcenters=x_centers,
        ycellcenters=y_centers,
    )


def _make_static_field_record(
    nrow: int,
    ncol: int,
    value: float,
    unit: str = "mm/day",
    dx: float = 10.0,
    dy: float = 10.0,
) -> FieldRecord:
    """Static (no time) xarray FieldRecord with uniform value."""
    x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
    y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])
    data_2d = np.full((nrow, ncol), value, dtype=float)
    ds = xr.Dataset(
        {"recharge": (("y", "x"), data_2d)},
        coords={"x": x_coords, "y": y_coords},
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit=unit,
        data=ds,
        bbox=(0.0, 0.0, ncol * dx, nrow * dy),
        crs="EPSG:2154",
    )


def _make_temporal_field_record(
    nrow: int,
    ncol: int,
    values_per_day: list[float],
    start_date: str = "2020-01-01",
    unit: str = "mm/day",
    dx: float = 10.0,
    dy: float = 10.0,
) -> FieldRecord:
    """Time-varying xarray FieldRecord, one value per day (uniform spatially)."""
    ntime = len(values_per_day)
    times = pd.date_range(start_date, periods=ntime, freq="D")
    x_coords = np.array([(j + 0.5) * dx for j in range(ncol)])
    y_coords = np.array([(nrow - i - 0.5) * dy for i in range(nrow)])

    data_3d = np.zeros((ntime, nrow, ncol), dtype=float)
    for t_idx, val in enumerate(values_per_day):
        data_3d[t_idx, :, :] = val

    ds = xr.Dataset(
        {"recharge": (("time", "y", "x"), data_3d)},
        coords={"time": times, "x": x_coords, "y": y_coords},
    )
    return FieldRecord(
        variable="recharge",
        source="test",
        unit=unit,
        data=ds,
        bbox=(0.0, 0.0, ncol * dx, nrow * dy),
        crs="EPSG:2154",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 1) + timedelta(days=ntime - 1),
        frequency="D",
    )


def _make_simulation_window(
    start: str,
    end: str,
    step_value: int = 1,
    step_unit: str = "month",
    coverage_policy: str = "ignore",
) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        step_value=step_value,
        step_unit=step_unit,
        coverage_policy=coverage_policy,
    )

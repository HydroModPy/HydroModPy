"""Soil reservoir forcing: daily recharge (mm/day) on the SAFRAN grid, per soil column.

compute_soil_forcings runs the reservoir kernel on a precipitation grid and an ETP grid
(mm/day), optionally spread into capacity classes by a soil capacity raster (mm). It
returns recharge, unmet ETP and runoff as gridded records, and the per-column fluxes.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest
import rasterio
import xarray as xr
from rasterio.transform import from_origin

import hydromodpy.model.forcing.soil_forcing as soil_forcing
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import RU_LADDER_MM, compute_soil_forcings, ru_ladder

CRS = "EPSG:2154"
CELL_M = 1000.0  # SAFRAN cells are laid out 1000 m apart in the raster cases


def window_of(days: pd.DatetimeIndex) -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )


def grid_record(variable, values, days, x, y, bbox=None) -> FieldRecord:
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
    )
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=bbox or (x.min(), y.min(), x.max(), y.max()),
        crs=CRS,
        date_start=days[0],
        date_end=days[-1],
    )


def padded(x, y):
    """The bbox of SAFRAN cells centred on x and y, half a cell larger on each side."""
    half = CELL_M / 2
    return (x.min() - half, y.min() - half, x.max() + half, y.max() + half)


def run_soil(precipitation, etp, days, x, y, *, ru=150.0, spinup="none", bbox=None, **kwargs):
    return compute_soil_forcings(
        precipitation=LoadResult(
            fields=[grid_record("precipitation", precipitation, days, x, y, bbox)]
        ),
        etp=LoadResult(fields=[grid_record("etp", etp, days, x, y, bbox)]),
        config=SoilReservoirConfig(ru=ru, spinup=spinup),
        window=window_of(days),
        model_crs=CRS,
        **kwargs,
    )


def capacity_raster(path, data, bbox, *, west, north, cell_m) -> LoadResult:
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=CRS,
        transform=from_origin(west, north, cell_m, cell_m),
    ) as dst:
        dst.write(data.astype("float32"), 1)
    record = FieldRecord(
        variable="soil_capacity", source="file", unit="mm", data=path, bbox=bbox, crs=CRS
    )
    return LoadResult(fields=[record])


def wet_winter_dry_summer(days):
    """Daily precipitation and ETP (mm/day) that drain the soil well below RU in summer."""
    doy = np.asarray(days.dayofyear, dtype=np.float64)
    rain_mean = 0.5 + 4.5 * np.clip(np.cos(2 * np.pi * (doy - 15) / 365.25), 0.0, None)
    precipitation = np.random.default_rng(5).gamma(1.2, rain_mean / 1.2)
    etp = 0.2 + 3.3 * np.clip(np.cos(2 * np.pi * (doy - 195) / 365.25), 0.0, None)
    return precipitation.reshape(-1, 1, 1), etp.reshape(-1, 1, 1)


def test_heterogeneous_capacity_recharges_more(tmp_path):
    # Pe = max(0, W - RU) is convex in RU, so classes of the same mean recharge at least as
    # much as the mean alone (Jensen). A lognormal RU with CV ~ 0.4 makes some classes saturate.
    x, y = np.array([0.0]), np.array([0.0])
    days = pd.date_range("2015-01-01", periods=3 * 365, freq="D")
    precipitation, etp = wet_winter_dry_summer(days)
    data = np.random.default_rng(11).lognormal(mean=np.log(150.0), sigma=0.4, size=(80, 80))
    bbox = padded(x, y)
    raster = capacity_raster(tmp_path / "ru.tif", data, bbox, west=-500.0, north=500.0, cell_m=12.5)

    def basin_recharge(soil_capacity):
        forcings = run_soil(precipitation, etp, days, x, y, bbox=bbox, soil_capacity=soil_capacity)
        return float((forcings.fluxes.recharge @ forcings.columns.basin_weight).sum())

    assert basin_recharge(raster) > basin_recharge(None) * 1.001


def test_flat_capacity_raster_is_the_uniform_soil(tmp_path):
    # Every pixel is 200 mm, so every class gets ru_shape = 1 and nothing is spread.
    x, y = np.array([0.0, CELL_M]), np.array([0.0])
    days = pd.date_range("2015-01-01", periods=30, freq="D")
    precipitation = np.random.default_rng(7).gamma(2.0, 3.0, size=(len(days), 1, 2))
    etp = np.full((len(days), 1, 2), 2.0)
    bbox = padded(x, y)
    raster = capacity_raster(
        tmp_path / "ru.tif", np.full((40, 60), 200.0), bbox, west=-500.0, north=500.0, cell_m=25.0
    )

    with_raster = run_soil(precipitation, etp, days, x, y, bbox=bbox, soil_capacity=raster)
    without_raster = run_soil(precipitation, etp, days, x, y, bbox=bbox)

    np.testing.assert_allclose(with_raster.columns.ru_shape, 1.0, atol=1e-12)
    recharge_with = with_raster.recharge.fields[0].data["recharge"].values
    recharge_without = without_raster.recharge.fields[0].data["recharge"].values
    np.testing.assert_allclose(recharge_with, recharge_without, atol=1e-12)


def test_raster_keeps_the_declared_mean_ru(tmp_path):
    # A skewed raster: no two SAFRAN cells share a distribution.
    x, y = np.array([0.0, 1000.0, 2000.0]), np.array([0.0, 1000.0])
    days = pd.date_range("2015-01-01", periods=10, freq="D")
    zeros = np.zeros((len(days), 2, 3))
    bbox = padded(x, y)
    data = np.random.default_rng(3).lognormal(mean=4.7, sigma=0.4, size=(80, 120))
    raster = capacity_raster(
        tmp_path / "ru.tif", data, bbox, west=-500.0, north=1500.0, cell_m=25.0
    )

    forcings = run_soil(zeros, zeros, days, x, y, ru=150.0, bbox=bbox, soil_capacity=raster)

    columns = forcings.columns
    assert np.ptp(columns.ru_shape) > 0.01  # the raster is genuinely heterogeneous
    weighted_mean_ru = float(np.sum(columns.basin_weight * 150.0 * columns.ru_shape))
    assert weighted_mean_ru == pytest.approx(150.0, abs=1e-9)


def two_years_with_a_dry_season():
    days = pd.date_range("2015-01-01", "2016-12-31", freq="D")
    is_winter = (days.dayofyear < 90) | (days.dayofyear >= 270)
    precipitation = np.where(is_winter, 4.0, 0.0)[:, np.newaxis, np.newaxis]
    etp = np.where(is_winter, 0.2, 3.0)[:, np.newaxis, np.newaxis]
    x, y = np.array([0.0]), np.array([0.0])
    return run_soil(
        precipitation, etp, days, x, y, spinup="first_year", bbox=(0.0, 0.0, 100.0, 100.0)
    )


def test_ru_ladder_covers_every_declared_ru():
    ladder = ru_ladder(two_years_with_a_dry_season())

    assert tuple(ru for ru, _ in ladder) == RU_LADDER_MM


def test_ru_rung_that_never_settles_is_nan(monkeypatch):
    forcings = two_years_with_a_dry_season()
    real_spinup_or_full = soil_forcing._spinup_or_full
    unsettled_ru_mm = 200.0 * forcings.columns.ru_shape[0]

    def fake_spinup_or_full(config, parameters, precipitation, etp):
        state, spinup_result = real_spinup_or_full(config, parameters, precipitation, etp)
        if parameters.ru_mm[0] == unsettled_ru_mm:
            spinup_result = dataclasses.replace(spinup_result, settled=False)
        return state, spinup_result

    monkeypatch.setattr(soil_forcing, "_spinup_or_full", fake_spinup_or_full)

    ladder = ru_ladder(forcings)

    assert math.isnan(dict(ladder)[200.0])
    assert all(not math.isnan(value) for ru, value in ladder if ru != 200.0)


def test_column_count_is_the_cell_count():
    days = pd.date_range("2015-01-01", periods=20, freq="D")
    x, y = np.array([0.0, 100.0, 200.0]), np.array([500.0, 300.0])
    # Every cell carries a distinct constant precipitation, so a column identifies its cell.
    cell_value = np.arange(6, dtype=np.float64).reshape(2, 3)
    precipitation = np.broadcast_to(cell_value, (len(days), 2, 3)).copy()

    forcings = run_soil(precipitation, np.zeros((len(days), 2, 3)), days, x, y, ru=100.0)

    np.testing.assert_array_equal(forcings.columns.cell_index, np.arange(6))


def test_run_days_cover_the_window():
    days = pd.date_range("2015-01-01", periods=400, freq="D")
    x, y = np.array([0.0, 100.0, 200.0]), np.array([100.0, 0.0])
    precipitation = np.random.default_rng(1).gamma(2.0, 2.0, size=(len(days), 2, 3))

    forcings = run_soil(
        precipitation, np.full((len(days), 2, 3), 2.0), days, x, y, spinup="first_year"
    )

    np.testing.assert_array_equal(forcings.days, days.values)


def test_file_backed_record_stays_a_path(tmp_path):
    # FieldRecord.dataset opens a path and caches it on the shared record. The reservoir must
    # open the file itself and leave the record as it found it.
    days = pd.date_range("2015-01-01", periods=15, freq="D")
    x, y = np.array([0.0, 100.0]), np.array([100.0, 0.0])
    records = {}
    for variable, value in (("precipitation", 5.0), ("etp", 2.0)):
        values = np.full((len(days), 2, 2), value)
        dataset = xr.Dataset(
            {variable: (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
        )
        path = tmp_path / f"{variable}.nc"
        dataset.to_netcdf(path)
        record = grid_record(variable, values, days, x, y, bbox=(0.0, 0.0, 100.0, 100.0))
        records[variable] = dataclasses.replace(record, data=path)

    compute_soil_forcings(
        precipitation=LoadResult(fields=[records["precipitation"]]),
        etp=LoadResult(fields=[records["etp"]]),
        config=SoilReservoirConfig(ru=100.0, spinup="none"),
        window=window_of(days),
        model_crs=CRS,
    )

    assert records["precipitation"].data == tmp_path / "precipitation.nc"
    assert records["etp"].data == tmp_path / "etp.nc"

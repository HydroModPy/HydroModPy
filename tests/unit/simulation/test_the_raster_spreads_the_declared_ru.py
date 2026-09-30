"""The raster spreads ru into classes without moving the basin mean.

``ru`` stays the mean capacity of the SAFRAN cells (spec section 1.7): the
raster only gives it a shape. The basin_weight-weighted mean of the per-column
``ru`` (``config.ru * ru_shape``) equals ``config.ru`` exactly, whatever the
raster's own heterogeneity.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.transform import from_origin

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings

_CRS = "EPSG:2154"
_X = np.array([0.0, 1000.0, 2000.0])
_Y = np.array([0.0, 1000.0])


def _grid_result(variable: str, values: np.ndarray, *, days: pd.DatetimeIndex) -> LoadResult:
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)},
        coords={"time": days, "y": _Y, "x": _X},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(_X.min() - 500.0, _Y.min() - 500.0, _X.max() + 500.0, _Y.max() + 500.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _write_capacity_raster(path: Path) -> LoadResult:
    # A skewed, cell-dependent raster: no two SAFRAN cells share a distribution.
    rng = np.random.default_rng(3)
    data = rng.lognormal(mean=4.7, sigma=0.4, size=(80, 120)).astype("float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=_CRS,
        transform=from_origin(-500.0, 1500.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    record = FieldRecord(
        variable="soil_capacity",
        source="custom",
        unit="mm",
        data=path,
        bbox=(-500.0, -500.0, 2500.0, 1500.0),
        crs=_CRS,
    )
    return LoadResult(fields=[record])


def test_the_weighted_mean_ru_equals_the_declared_ru(tmp_path: Path) -> None:
    soil_capacity = _write_capacity_raster(tmp_path / "ru.tif")
    days = pd.date_range("2015-01-01", periods=10, freq="D")
    precipitation = np.zeros((len(days), 2, 3))
    etp = np.zeros((len(days), 2, 3))
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=150.0, spinup="none")
    forcings = compute_soil_forcings(
        precipitation=_grid_result("precipitation", precipitation, days=days),
        etp=_grid_result("etp", etp, days=days),
        config=config,
        window=window,
        model_crs=_CRS,
        soil_capacity=soil_capacity,
    )

    columns = forcings.columns
    # The raster is genuinely heterogeneous: not every column shares one ru.
    assert np.ptp(columns.ru_shape) > 0.01
    ru_mm = config.ru * columns.ru_shape
    weighted_mean_ru = float(np.sum(columns.basin_weight * ru_mm))
    assert abs(weighted_mean_ru - config.ru) < 1e-9

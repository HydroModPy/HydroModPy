"""A constant soil capacity raster carries no shape.

Every pixel of ``[data.soil_capacity]`` sorts into one value, so every class
of every cell gets ``ru_shape = 1`` and the recharge aggregated back onto the
grid matches the uniform (no-raster) case: the raster only spreads a shape,
and a flat raster has none.
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
_X = np.array([0.0, 1000.0])  # two SAFRAN cells, one row
_Y = np.array([0.0])


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


def _write_capacity_raster(path: Path, value: float) -> LoadResult:
    data = np.full((40, 60), value, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=_CRS,
        transform=from_origin(-500.0, 500.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    record = FieldRecord(
        variable="soil_capacity",
        source="custom",
        unit="mm",
        data=path,
        bbox=(-500.0, -500.0, 1500.0, 500.0),
        crs=_CRS,
    )
    return LoadResult(fields=[record])


def _days() -> pd.DatetimeIndex:
    return pd.date_range("2015-01-01", periods=30, freq="D")


def _run(*, soil_capacity: LoadResult | None, ru: float, tmp_path: Path):
    days = _days()
    rng = np.random.default_rng(7)
    precipitation = rng.gamma(2.0, 3.0, size=(len(days), 1, 2))
    etp = np.full((len(days), 1, 2), 2.0)
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=ru, spinup="none")
    return compute_soil_forcings(
        precipitation=_grid_result("precipitation", precipitation, days=days),
        etp=_grid_result("etp", etp, days=days),
        config=config,
        window=window,
        model_crs=_CRS,
        soil_capacity=soil_capacity,
    )


def test_ru_shape_is_one_everywhere(tmp_path: Path) -> None:
    soil_capacity = _write_capacity_raster(tmp_path / "ru.tif", 200.0)
    forcings = _run(soil_capacity=soil_capacity, ru=150.0, tmp_path=tmp_path)

    np.testing.assert_allclose(forcings.columns.ru_shape, 1.0, atol=1e-12)


def test_the_aggregated_recharge_matches_the_uniform_case(tmp_path: Path) -> None:
    soil_capacity = _write_capacity_raster(tmp_path / "ru.tif", 200.0)
    with_raster = _run(soil_capacity=soil_capacity, ru=150.0, tmp_path=tmp_path)
    without_raster = _run(soil_capacity=None, ru=150.0, tmp_path=tmp_path)

    recharge_with = with_raster.recharge.fields[0].data["recharge"].values
    recharge_without = without_raster.recharge.fields[0].data["recharge"].values
    np.testing.assert_allclose(recharge_with, recharge_without, atol=1e-12)

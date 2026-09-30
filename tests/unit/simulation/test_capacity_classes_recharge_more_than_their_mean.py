"""Heterogeneous capacity recharges more than its mean (Jensen effect).

``Pe = max(0, W - RU)`` is convex and decreasing in ``RU``: spreading one
SAFRAN cell's capacity into classes of the same mean, instead of running the
cell on that mean alone, can only raise or hold the aggregate recharge, and
raises it whenever some classes saturate while others do not (spec section
1.7; the prototype measures a 4.1 % average effect).
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
_X = np.array([0.0])
_Y = np.array([0.0])
_CELL_HALF_SPAN = 500.0


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
        bbox=(
            _X[0] - _CELL_HALF_SPAN,
            _Y[0] - _CELL_HALF_SPAN,
            _X[0] + _CELL_HALF_SPAN,
            _Y[0] + _CELL_HALF_SPAN,
        ),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _write_capacity_raster(path: Path) -> LoadResult:
    # Lognormal RU, CV ~ 0.4 (spec section 1.7's own probe distribution).
    rng = np.random.default_rng(11)
    data = rng.lognormal(mean=np.log(150.0), sigma=0.4, size=(80, 80)).astype("float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=_CRS,
        transform=from_origin(-_CELL_HALF_SPAN, _CELL_HALF_SPAN, 12.5, 12.5),
    ) as dst:
        dst.write(data, 1)
    record = FieldRecord(
        variable="soil_capacity",
        source="custom",
        unit="mm",
        data=path,
        bbox=(-_CELL_HALF_SPAN, -_CELL_HALF_SPAN, _CELL_HALF_SPAN, _CELL_HALF_SPAN),
        crs=_CRS,
    )
    return LoadResult(fields=[record])


def _synthetic_climate(days: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """A wet-winter, dry-summer daily climate that drains the soil well below RU

    in summer (a real seasonal cycle, not a soil kept always full): the
    refill then overflows a small-capacity class before a large one.
    """
    doy = np.asarray(days.dayofyear, dtype=np.float64)
    rain_mean = 0.5 + 4.5 * np.clip(np.cos(2 * np.pi * (doy - 15) / 365.25), 0.0, None)
    rng = np.random.default_rng(5)
    precipitation = rng.gamma(1.2, rain_mean / 1.2)
    etp = 0.2 + 3.3 * np.clip(np.cos(2 * np.pi * (doy - 195) / 365.25), 0.0, None)
    return (
        precipitation.reshape(-1, 1, 1),
        etp.reshape(-1, 1, 1),
    )


def _basin_recharge(*, soil_capacity: LoadResult | None, tmp_path: Path) -> float:
    days = pd.date_range("2015-01-01", periods=3 * 365, freq="D")
    precipitation, etp = _synthetic_climate(days)
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
    basin_recharge = forcings.fluxes.recharge @ forcings.columns.basin_weight
    return float(basin_recharge.sum())


def test_the_heterogeneous_capacity_recharges_more(tmp_path: Path) -> None:
    soil_capacity = _write_capacity_raster(tmp_path / "ru.tif")
    with_raster = _basin_recharge(soil_capacity=soil_capacity, tmp_path=tmp_path)
    without_raster = _basin_recharge(soil_capacity=None, tmp_path=tmp_path)

    assert with_raster > without_raster * 1.001

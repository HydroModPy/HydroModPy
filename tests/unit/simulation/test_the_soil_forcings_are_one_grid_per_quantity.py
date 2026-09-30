"""The soil reservoir hands back one gridded FieldRecord per quantity.

``compute_soil_forcings`` reads one precipitation grid and one ETP grid and
returns three ``LoadResult``, each holding exactly one ``FieldRecord``: the
recharge, the unmet ETP and the runoff, all in mm/day on the precipitation
grid.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings

_CRS = "EPSG:2154"


def _grid_result(variable: str, values: np.ndarray, *, days: pd.DatetimeIndex, x, y) -> LoadResult:
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)},
        coords={"time": days, "y": y, "x": x},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(x.min(), y.min(), x.max(), y.max()),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _forcings():
    days = pd.date_range("2015-01-01", periods=400, freq="D")
    x = np.array([0.0, 100.0, 200.0])
    y = np.array([100.0, 0.0])
    rng = np.random.default_rng(1)
    precipitation = rng.gamma(2.0, 2.0, size=(len(days), 2, 3))
    etp = np.full((len(days), 2, 3), 2.0)
    precip_result = _grid_result("precipitation", precipitation, days=days, x=x, y=y)
    etp_result = _grid_result("etp", etp, days=days, x=x, y=y)
    window = ResolvedSimulationTimeWindow(
        start=days[0],
        end=days[-1],
        step_value=1,
        step_unit="day",
        coverage_policy="error",
    )
    config = SoilReservoirConfig(ru=150.0)
    forcings = compute_soil_forcings(
        precipitation=precip_result, etp=etp_result, config=config, window=window, model_crs=_CRS
    )
    return forcings, days, x, y


def test_each_output_holds_exactly_one_field() -> None:
    forcings, *_ = _forcings()
    assert len(forcings.recharge.fields) == 1
    assert len(forcings.residual_etp.fields) == 1
    assert len(forcings.runoff.fields) == 1


def test_every_field_is_in_millimetres_per_day() -> None:
    forcings, *_ = _forcings()
    assert forcings.recharge.fields[0].unit == "mm/day"
    assert forcings.residual_etp.fields[0].unit == "mm/day"
    assert forcings.runoff.fields[0].unit == "mm/day"


def test_every_field_has_time_y_x_dimensions() -> None:
    forcings, *_ = _forcings()
    for result in (forcings.recharge, forcings.residual_etp, forcings.runoff):
        dataset = result.fields[0].data
        assert set(dataset.dims) == {"time", "y", "x"}


def test_every_field_sits_on_the_precipitation_grid() -> None:
    forcings, days, x, y = _forcings()
    for result in (forcings.recharge, forcings.residual_etp, forcings.runoff):
        dataset = result.fields[0].data
        np.testing.assert_array_equal(dataset["x"].values, x)
        np.testing.assert_array_equal(dataset["y"].values, y)
        np.testing.assert_array_equal(dataset["time"].values, forcings.days)


def test_the_run_days_cover_the_whole_window() -> None:
    forcings, days, _x, _y = _forcings()
    np.testing.assert_array_equal(forcings.days, days.values)

"""Two trials with different ``runoff_lag`` are scored differently.

Mirrors ``test_two_trials_scored_discharge_differs_by_curve_number.py``: a
calibration trial rebuilds its own ``SoilForcings`` from its own config, and
``add_runoff_to_discharge`` reads ``ctx.setup.soil_forcings.runoff``, which
now carries the delayed curve-number share. Two ``compute_soil_forcings``
calls that differ only in ``runoff_lag``, piped the same way a trial's own
context would be, prove the trial recomputation path reaches the new term.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import xarray as xr

from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings

_CRS = "EPSG:2154"
_RAIN_MM_PER_DAY = 25.0
_CATCH_AREA_KM2 = 86.4


def _constant_grid(variable: str, value: float, *, days: pd.DatetimeIndex) -> LoadResult:
    values = np.full((days.size, 1, 1), value)
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)},
        coords={"time": days, "y": [0.0], "x": [0.0]},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _pulsed_grid(variable: str, *, days: pd.DatetimeIndex) -> LoadResult:
    values = np.zeros((days.size, 1, 1))
    values[0, 0, 0] = _RAIN_MM_PER_DAY
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)},
        coords={"time": days, "y": [0.0], "x": [0.0]},
    )
    record = FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )
    return LoadResult(fields=[record])


def _soil_forcings(runoff_lag: float):
    days = pd.date_range("2020-01-01", periods=10, freq="D")
    precipitation = _pulsed_grid("precipitation", days=days)
    etp = _constant_grid("etp", 0.0, days=days)
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(
        ru=100.0,
        spinup="none",
        curve_number=85.0,
        runoff_time=0.0,
        runoff_lag=runoff_lag,
    )
    return compute_soil_forcings(
        precipitation=precipitation, etp=etp, config=config, window=window, model_crs=_CRS
    )


def _scored_discharge(forcings) -> pd.Series:
    """The discharge a trial exposing ``forcings`` would be scored on, once."""
    baseflow = pd.Series(0.0, index=pd.DatetimeIndex(forcings.days[1:]), name="discharge")
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=None),
        setup=SimpleNamespace(
            geographic=SimpleNamespace(catch_area=_CATCH_AREA_KM2),
            soil_forcings=SimpleNamespace(runoff=forcings.runoff),
        ),
    )
    return add_runoff_to_discharge(baseflow, ctx)


def test_each_trial_recomputes_its_own_runoff_lag() -> None:
    off = _soil_forcings(0.0)
    on = _soil_forcings(3.0)

    off_runoff = off.runoff.fields[0].data["runoff"].to_numpy()
    on_runoff = on.runoff.fields[0].data["runoff"].to_numpy()

    assert not np.allclose(off_runoff, on_runoff)


def test_two_trials_get_different_scored_discharge_by_runoff_lag() -> None:
    unlagged_discharge = _scored_discharge(_soil_forcings(0.0))
    lagged_discharge = _scored_discharge(_soil_forcings(3.0))

    assert not np.allclose(unlagged_discharge.to_numpy(), lagged_discharge.to_numpy())

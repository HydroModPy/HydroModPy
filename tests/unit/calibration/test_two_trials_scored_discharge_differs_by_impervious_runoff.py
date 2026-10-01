"""Two trials with different ``impervious_fraction`` are scored differently.

A calibration trial rebuilds its own ``SoilForcings`` from its own config
(``TrialContext.fork`` calls ``apply_structural_updates_from_data``, which
calls ``compute_soil_forcings`` on the patched ``cfg.flow``), the same way it
already does for ``ru``. ``add_runoff_to_discharge`` -- the function
``composite.py`` calls once per trial, never twice -- then reads
``ctx.setup.soil_forcings.runoff`` and adds it to the scored discharge.

This test exercises that chain with a tiny synthetic soil case instead of a
full MODFLOW run: two ``compute_soil_forcings`` calls that differ only in
``impervious_fraction``, each piped through ``add_runoff_to_discharge`` the
way a trial's own context would be. The expected volume is exact because the
kernel's runoff is ``impervious_fraction * precipitation``
(``hydromodpy/physics/hydrology/soil_reservoir/kernel.py``), so a constant
rain and a known area give a closed-form discharge difference.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.calibration.metrics.series import add_runoff_to_discharge
from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import compute_soil_forcings

_CRS = "EPSG:2154"
_RAIN_MM_PER_DAY = 10.0
# 1 mm/day over 86.4 km2 is exactly 1 m3/s: 1e-3 * 8.64e7 / 86400.
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


def _soil_forcings(impervious_fraction: float):
    days = pd.date_range("2020-01-01", periods=10, freq="D")
    precipitation = _constant_grid("precipitation", _RAIN_MM_PER_DAY, days=days)
    etp = _constant_grid("etp", 0.0, days=days)
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=100.0, spinup="none", impervious_fraction=impervious_fraction)
    return compute_soil_forcings(
        precipitation=precipitation, etp=etp, config=config, window=window, model_crs=_CRS
    )


def _scored_discharge(forcings) -> pd.Series:
    """The discharge a trial exposing ``forcings`` would be scored on, once.

    Drops the first day: without a ``setup.time_grid`` to bound it, the
    period-mean rule this helper uses has no left edge for the first period
    and reports a gap there (see ``core.time.period_aggregation``), not a
    missing wiring of the runoff.
    """
    baseflow = pd.Series(0.0, index=pd.DatetimeIndex(forcings.days[1:]), name="discharge")
    ctx = SimpleNamespace(
        loaded_data=SimpleNamespace(runoff=None),
        setup=SimpleNamespace(
            geographic=SimpleNamespace(catch_area=_CATCH_AREA_KM2),
            soil_forcings=SimpleNamespace(runoff=forcings.runoff),
        ),
    )
    return add_runoff_to_discharge(baseflow, ctx)


def test_each_trial_recomputes_its_own_runoff() -> None:
    low = _soil_forcings(0.0)
    high = _soil_forcings(0.08)

    low_runoff = low.runoff.fields[0].data["runoff"].to_numpy()
    high_runoff = high.runoff.fields[0].data["runoff"].to_numpy()

    assert low_runoff == pytest.approx(0.0)
    assert high_runoff == pytest.approx(0.08 * _RAIN_MM_PER_DAY)


def test_two_trials_get_different_scored_discharge_by_the_expected_volume() -> None:
    low_discharge = _scored_discharge(_soil_forcings(0.0))
    high_discharge = _scored_discharge(_soil_forcings(0.08))

    delta = high_discharge - low_discharge
    # 0.08 x 10 mm/day sealed runoff, over 86.4 km2, is 0.8 m3/s: the exact
    # volume the impervious fraction alone adds, added once.
    expected_m3_per_s = 0.08 * _RAIN_MM_PER_DAY * 1e-3 * (_CATCH_AREA_KM2 * 1e6) / 86400.0
    assert delta.to_numpy() == pytest.approx(expected_m3_per_s)

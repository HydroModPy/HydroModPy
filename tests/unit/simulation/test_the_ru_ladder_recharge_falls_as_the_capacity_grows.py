"""A deeper soil retains more water, so its basin recharge falls.

``ru_ladder`` reruns the kernel for each value of ``RU_LADDER_MM``, other
parameters fixed. On a climate with a dry season, a larger reservoir carries
more water through it and returns less to the water table.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import xarray as xr

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.data.contracts import FieldRecord, LoadResult
from hydromodpy.physics.hydrology.soil_reservoir.config import SoilReservoirConfig
from hydromodpy.simulation.soil_recharge import RU_LADDER_MM, compute_soil_forcings, ru_ladder

_CRS = "EPSG:2154"


def _grid_record(variable: str, values: np.ndarray, *, days, x, y) -> FieldRecord:
    dataset = xr.Dataset(
        {variable: (("time", "y", "x"), values)}, coords={"time": days, "y": y, "x": x}
    )
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/day",
        data=dataset,
        bbox=(0.0, 0.0, 100.0, 100.0),
        crs=_CRS,
        date_start=days[0],
        date_end=days[-1],
    )


def _forcings():
    days = pd.date_range("2015-01-01", "2016-12-31", freq="D")
    doy = np.array([d.dayofyear for d in days])
    is_winter = (doy < 90) | (doy >= 270)
    precipitation = np.where(is_winter, 4.0, 0.0)[:, np.newaxis, np.newaxis]
    etp = np.where(is_winter, 0.2, 3.0)[:, np.newaxis, np.newaxis]
    x = np.array([0.0])
    y = np.array([0.0])

    precip_result = LoadResult(
        fields=[_grid_record("precipitation", precipitation, days=days, x=x, y=y)]
    )
    etp_result = LoadResult(fields=[_grid_record("etp", etp, days=days, x=x, y=y)])
    window = ResolvedSimulationTimeWindow(
        start=days[0], end=days[-1], step_value=1, step_unit="day", coverage_policy="error"
    )
    config = SoilReservoirConfig(ru=150.0, spinup="first_year")
    return compute_soil_forcings(
        precipitation=precip_result, etp=etp_result, config=config, window=window, model_crs=_CRS
    )


def test_the_ladder_covers_every_declared_ru() -> None:
    forcings = _forcings()
    ladder = ru_ladder(forcings)
    assert tuple(ru for ru, _ in ladder) == RU_LADDER_MM


def test_recharge_falls_as_ru_grows() -> None:
    forcings = _forcings()
    ladder = ru_ladder(forcings)
    recharges = [value for _ru, value in ladder]
    assert all(a > b for a, b in zip(recharges, recharges[1:]))


def test_a_rung_whose_spinup_never_settles_reports_nan_not_a_silent_number(
    monkeypatch,
) -> None:
    import hydromodpy.simulation.soil_recharge as mod

    forcings = _forcings()
    real_spinup_or_full = mod._spinup_or_full
    unsettled_ru_mm = 200.0 * forcings.columns.ru_shape[0]

    def fake_spinup_or_full(config, parameters, precipitation, etp):
        state, spinup_result = real_spinup_or_full(config, parameters, precipitation, etp)
        if parameters.ru_mm[0] == unsettled_ru_mm:
            spinup_result = dataclasses.replace(spinup_result, settled=False)
        return state, spinup_result

    monkeypatch.setattr(mod, "_spinup_or_full", fake_spinup_or_full)

    ladder = mod.ru_ladder(forcings)
    values = dict(ladder)

    assert math.isnan(values[200.0])
    assert all(not math.isnan(v) for ru, v in ladder if ru != 200.0)

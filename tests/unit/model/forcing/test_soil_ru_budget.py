"""The capacity ru that closes recharge + runoff against the gauge (depths in mm).

The gauge of each test is built from the soil itself at a known ru, so the
search has a right answer to find. The other tests check the refusals and the
spread the module prints beside the value.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.model.forcing.soil_columns import SoilColumns
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.forcing.soil_forcing import SoilForcings, basin_water_out, soil_parameters
from hydromodpy.model.forcing.soil_ru_budget import BISECTION_TOLERANCE_MM, ru_closing_budget
from hydromodpy.model.soil.kernel import full_soil, run_soil_balance


def weather_forcings(
    n_years: int = 6, *, n_columns: int = 3, method: str = "fao56"
) -> SoilForcings:
    """A few columns under a wet winter and a dry summer, the same every year."""
    days = pd.date_range("2010-01-01", periods=int(365.25 * n_years), freq="D")
    rng = np.random.default_rng(11)
    day_of_year = days.dayofyear.to_numpy()[:, None]
    precipitation = rng.gamma(0.6, 7.0, (len(days), n_columns)) * (
        rng.random((len(days), n_columns)) < 0.5
    )
    etp = np.broadcast_to(
        np.clip(2.0 + 1.8 * np.sin(2 * np.pi * (day_of_year - 100) / 365), 0, None),
        (len(days), n_columns),
    ).copy()
    config = SoilReservoirConfig(ru=100.0, method=method)
    columns = SoilColumns(
        cell_index=np.arange(n_columns),
        class_index=np.zeros(n_columns, dtype=np.int64),
        x=np.zeros(n_columns),
        y=np.zeros(n_columns),
        ru_shape=np.linspace(0.8, 1.2, n_columns),
        cell_fraction=np.ones(n_columns),
        basin_weight=np.full(n_columns, 1.0 / n_columns),
    )
    params = soil_parameters(config, config.ru * columns.ru_shape)
    return SoilForcings(
        recharge=None,
        residual_etp=None,
        runoff=None,
        days=days.values,
        precipitation=precipitation,
        etp=etp,
        fluxes=run_soil_balance(precipitation, etp, params, full_soil(params)),
        columns=columns,
        config=config,
        parameters=params,
        spinup_cycles=0,
        never_full_columns=0,
        crs="EPSG:2154",
    )


def gauge_at(forcings: SoilForcings, ru: float) -> np.ndarray:
    recharge, runoff = basin_water_out(forcings, ru)
    return recharge + runoff


@pytest.mark.parametrize("method", ["fao56", "thornthwaite", "dingman", "edijatno_michel"])
def test_the_search_finds_the_ru_the_gauge_was_built_with(method):
    forcings = weather_forcings(method=method)

    closure = ru_closing_budget(forcings, gauge_at(forcings, 137.0))

    assert closure.reason is None
    assert closure.ru_mm == pytest.approx(137.0, abs=BISECTION_TOLERANCE_MM)


def test_the_value_comes_with_its_spread_and_its_sensitivities():
    forcings = weather_forcings()
    closure = ru_closing_budget(forcings, gauge_at(forcings, 137.0))

    low, high = closure.band_mm
    assert low <= closure.ru_mm + 15 and closure.ru_mm - 15 <= high
    # More rain asks a larger soil to hold the same outflow, a larger gauge a smaller one.
    assert closure.rain_plus_5_mm > closure.ru_mm > closure.rain_minus_5_mm
    assert closure.gauge_minus_5_mm > closure.ru_mm > closure.gauge_plus_5_mm
    assert closure.per_10_mm_evaporation_mm < 0


def test_a_gap_in_the_gauge_drops_its_days_and_keeps_the_answer():
    forcings = weather_forcings()
    gauge = gauge_at(forcings, 137.0)
    gauge[400:420] = np.nan

    closure = ru_closing_budget(forcings, gauge)

    assert closure.ru_mm == pytest.approx(137.0, abs=2.0)


def test_one_gauged_year_is_refused():
    forcings = weather_forcings()
    gauge = gauge_at(forcings, 137.0)
    gauge[365:] = np.nan

    closure = ru_closing_budget(forcings, gauge)

    assert closure.ru_mm is None
    assert "needs 2 at least" in closure.reason


def test_a_gauge_no_capacity_can_match_is_refused():
    forcings = weather_forcings()

    closure = ru_closing_budget(forcings, np.full(len(forcings.days), 50.0))

    assert closure.ru_mm is None
    assert "no capacity between 0 and 1000 mm closes the budget" in closure.reason


def test_the_infiltration_ratio_leaves_the_closing_ru_where_it_was():
    from dataclasses import replace

    forcings = weather_forcings()
    gauge = gauge_at(forcings, 137.0)
    split = replace(forcings, config=forcings.config.model_copy(update={"infiltration_ratio": 0.6}))

    # The ratio moves water from the recharge to the runoff, and the gauge sees both.
    assert ru_closing_budget(split, gauge).ru_mm == pytest.approx(
        ru_closing_budget(forcings, gauge).ru_mm
    )

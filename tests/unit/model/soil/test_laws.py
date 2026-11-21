"""Storage laws of the soil methods, snow and seasonal kc (depths in mm, times in days).

Every law shares one day of water between ETR, the soil store and the excess.
The tests check the balance of each law on its own and inside the full kernel,
the closed forms of each method, and the shell options every method shares.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.soil.kernel import (
    SoilParameters,
    balance_residual,
    full_soil,
    run_soil_balance,
    seasonal_kc,
    snow_step,
)
from hydromodpy.model.soil.laws import SOIL_METHODS, dingman, edijatno_michel, fao56, thornthwaite
from tests._helpers.tolerances import tol

METHODS = list(SOIL_METHODS)


def random_day(seed: int, n: int = 400):
    """Soil, inflow and demand of one day on ``n`` columns, a third of them without capacity."""
    rng = np.random.default_rng(seed)
    ru = rng.uniform(0.0, 300.0, n)
    ru[: n // 3] = 0.0
    soil = rng.uniform(0.0, 1.0, n) * ru
    inflow = rng.gamma(0.7, 8.0, n) * (rng.random(n) < 0.6)
    demand = rng.uniform(0.0, 6.0, n)
    return soil, inflow, demand, ru


@pytest.mark.parametrize("method", METHODS)
def test_each_law_closes_its_day_and_stays_in_bounds(method):
    soil, inflow, demand, ru = random_day(1)
    before = [a.copy() for a in (soil, inflow, demand, ru)]

    etr, soil_end, excess = SOIL_METHODS[method].law(soil, inflow, demand, ru, 0.45)

    np.testing.assert_allclose(soil + inflow, etr + soil_end + excess, rtol=0, atol=1e-9)
    assert np.all(etr >= -1e-12)
    assert np.all(etr <= demand + 1e-12)
    assert np.all(excess >= -1e-12)
    assert np.all(soil_end >= -1e-12)
    assert np.all(soil_end <= ru + 1e-9)
    for original, now in zip(before, (soil, inflow, demand, ru), strict=True):
        np.testing.assert_array_equal(original, now)


@pytest.mark.parametrize("method", METHODS)
def test_a_column_without_capacity_passes_on_what_it_does_not_evaporate(method):
    zero = np.zeros(2)
    etr, soil_end, excess = SOIL_METHODS[method].law(
        zero, np.array([10.0, 1.0]), np.array([3.0, 3.0]), zero, 0.45
    )
    np.testing.assert_allclose(etr, [3.0, 1.0])
    np.testing.assert_allclose(soil_end, [0.0, 0.0])
    np.testing.assert_allclose(excess, [7.0, 0.0])


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("kc", [0.7, 1.0, 1.3])
def test_every_method_closes_the_kernel_balance(method, kc):
    rng = np.random.default_rng(3)
    n_days, n_columns = 730, 12
    precipitation = rng.gamma(0.6, 7.0, (n_days, n_columns)) * (
        rng.random((n_days, n_columns)) < 0.5
    )
    day = np.arange(n_days)[:, None]
    etp = np.broadcast_to(
        np.clip(2.0 + 1.8 * np.sin(2 * np.pi * (day - 100) / 365), 0, None), (n_days, n_columns)
    ).copy()
    ru = rng.uniform(0.0, 300.0, n_columns)
    ru[:2] = 0.0
    params = SoilParameters(
        ru_mm=ru,
        alpha=0.45,
        kc=kc,
        impervious_fraction=0.1,
        bypass_fraction=0.05,
        transit_time_days=4.0,
        curve_number=80.0,
        method=method,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    residual = balance_residual(precipitation, fluxes)

    assert np.max(np.abs(residual.sum(axis=0)) / precipitation.sum(axis=0)) < tol(
        "soil_reservoir_kernel_balance"
    )
    assert np.all(fluxes.recharge >= -1e-12)


def test_thornthwaite_is_fao56_with_no_water_stress():
    soil, inflow, demand, ru = random_day(2)
    expected = thornthwaite(soil, inflow, demand, ru, 0.45)
    # alpha -> 0 removes the stress line: the full demand is met while water is left.
    almost = fao56(soil, inflow, demand, ru, 1e-12)
    for a, b in zip(expected, almost, strict=True):
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-9)


def test_dingman_empties_the_soil_as_an_exponential_on_dry_days():
    ru, soil0, demand, n = np.array([150.0]), np.array([120.0]), np.array([3.0]), 40
    soil = soil0
    for _ in range(n):
        _, soil, excess = dingman(soil, np.zeros(1), demand, ru, 0.45)
        assert excess[0] == 0.0
    np.testing.assert_allclose(soil, soil0 * np.exp(-n * demand / ru), rtol=1e-12)


def test_dingman_meets_the_demand_and_overflows_on_a_wet_day():
    etr, soil, excess = dingman(
        np.array([140.0]), np.array([20.0]), np.array([4.0]), np.array([150.0]), 0.45
    )
    np.testing.assert_allclose([etr[0], soil[0], excess[0]], [4.0, 150.0, 6.0])


def test_edijatno_michel_fills_and_empties_by_the_tanh_forms():
    ru, soil = 100.0, 50.0
    etr, filled, excess = edijatno_michel(
        np.array([soil]), np.array([22.0]), np.array([2.0]), np.array([ru]), 0.45
    )
    t = np.tanh(20.0 / ru)
    expected = ru * (soil / ru + t) / (1 + soil / ru * t)
    np.testing.assert_allclose(
        [etr[0], filled[0], excess[0]], [2.0, expected, 20.0 - (expected - soil)]
    )
    assert 0.0 < excess[0] < 20.0  # part of the net rain leaves before the store is full

    etr, emptied, excess = edijatno_michel(
        np.array([soil]), np.array([1.0]), np.array([5.0]), np.array([ru]), 0.45
    )
    t = np.tanh(4.0 / ru)
    expected = soil * (1 - t) / (1 + (1 - soil / ru) * t)
    np.testing.assert_allclose(
        [emptied[0], excess[0], etr[0]], [expected, 0.0, 1.0 + soil - expected]
    )


def test_edijatno_michel_tests_the_branch_on_the_demand_so_kc_keeps_the_balance():
    # ESPERE compares the inflow to ETP, not kc x ETP: an inflow between the two
    # would enter the rainy branch with a negative net rain. Here it does not.
    etr, soil_end, excess = edijatno_michel(
        np.array([60.0]), np.array([4.5]), np.array([5.0]), np.array([100.0]), 0.45
    )
    assert excess[0] == 0.0
    assert soil_end[0] < 60.0
    np.testing.assert_allclose(60.0 + 4.5, etr[0] + soil_end[0] + excess[0])


def snowy_params(**changes) -> SoilParameters:
    base = dict(
        ru_mm=np.array([100.0]),
        alpha=0.45,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        snow_melt_start_c=0.0,
        snow_melt_full_c=6.0,
    )
    return SoilParameters(**(base | changes))


@pytest.mark.parametrize(
    ("temperature", "liquid", "pack"),
    [
        pytest.param(-3.0, 0.0, 30.0, id="all snow below melt_start"),
        pytest.param(3.0, 0.5 * 10 + 0.5 * (20 + 5), 0.5 * (20 + 5), id="half melts at 3 degC"),
        pytest.param(8.0, 10.0 + 20.0, 0.0, id="all melts above melt_full"),
    ],
)
def test_snow_step_follows_the_linear_melt_of_espere(temperature, liquid, pack):
    got_liquid, got_pack = snow_step(
        np.array([20.0]), np.array([10.0]), np.array([temperature]), snowy_params()
    )
    np.testing.assert_allclose([got_liquid[0], got_pack[0]], [liquid, pack])
    np.testing.assert_allclose(got_liquid + got_pack, 30.0)


def test_snow_holds_winter_precipitation_and_the_balance_still_closes():
    n_days = 365
    day = np.arange(n_days)
    precipitation = np.full((n_days, 1), 3.0)
    etp = np.full((n_days, 1), 1.0)
    temperature = (8.0 + 10.0 * np.cos(2 * np.pi * day / 365))[:, None]  # summer, winter, summer
    params = snowy_params()

    fluxes = run_soil_balance(
        precipitation, etp, params, full_soil(params), temperature=temperature
    )

    assert fluxes.snow_storage.max() > 50.0
    assert fluxes.snow_storage[-1, 0] < fluxes.snow_storage.max()
    residual = balance_residual(precipitation, fluxes)
    assert np.max(np.abs(residual)) / precipitation.max() < tol("soil_reservoir_kernel_balance")


def test_seasonal_kc_draws_the_trapezoid_of_the_growing_season():
    days = np.arange(np.datetime64("2021-01-01"), np.datetime64("2022-01-01"))
    kc = seasonal_kc(days, 0.6, 1.2, (4, 6, 8, 10))

    def on(date: str) -> float:
        return float(kc[(np.datetime64(date) - days[0]).astype(int)])

    assert on("2021-02-01") == pytest.approx(0.6)
    assert on("2021-04-01") == pytest.approx(0.6)
    assert 0.6 < on("2021-05-01") < 1.2
    assert on("2021-06-01") == pytest.approx(1.2)
    assert on("2021-07-20") == pytest.approx(1.2)
    assert on("2021-10-01") == pytest.approx(0.6)


def test_seasonal_kc_takes_a_winter_crop_across_the_new_year():
    days = np.arange(np.datetime64("2021-01-01"), np.datetime64("2022-01-01"))
    kc = seasonal_kc(days, 0.5, 1.0, (10, 3, 6, 7))
    assert 0.5 < kc[0] < 1.0  # still rising in January
    assert kc[(np.datetime64("2021-04-15") - days[0]).astype(int)] == pytest.approx(1.0)
    assert kc[(np.datetime64("2021-08-15") - days[0]).astype(int)] == pytest.approx(0.5)


def test_a_seasonal_kc_reaches_the_daily_demand():
    n_days = 365
    days = np.arange(np.datetime64("2021-01-01"), np.datetime64("2022-01-01"))
    kc = seasonal_kc(days, 0.5, 1.5, (4, 6, 8, 10))
    precipitation = np.full((n_days, 1), 20.0)
    etp = np.full((n_days, 1), 2.0)
    params = snowy_params(snow_melt_start_c=None, snow_melt_full_c=None, ru_mm=np.array([50.0]))

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params), kc_by_day=kc)

    np.testing.assert_allclose(fluxes.etr[:, 0], kc * 2.0)


def test_snow_without_a_temperature_is_refused():
    params = snowy_params()
    with pytest.raises(ValueError, match="no daily temperature"):
        run_soil_balance(np.ones((3, 1)), np.ones((3, 1)), params, full_soil(params))

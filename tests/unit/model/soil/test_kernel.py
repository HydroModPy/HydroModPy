"""Daily soil water balance of a column (all depths in mm, times in days).

The soil bucket of capacity ru_mm feeds a transit store (recharge) and, with a
curve number, a runoff store and an optional pure lag. The tests check closed
forms, the water balance and the order of the daily operations.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.soil.kernel import (
    SoilParameters,
    SoilState,
    annual_budget,
    apply_runoff_lag,
    balance_residual,
    full_soil,
    route_linear_reservoir,
    run_soil_balance,
    soil_step,
    spinup_state,
)
from tests._helpers.tolerances import tol

IMPULSE_TOL = "soil_transit_store_impulse__max_absolute_error_against_q_0_50_1_k_a_q_t_1_50_k_a_2_exp_t_1_k_mm"
TRANSIT_TIMES_DAYS = [0.5, 2.0, 5.0, 20.0, 30.0]


def soil_params(ru_mm, **changes) -> SoilParameters:
    """A soil with no sealed share, no by-pass, no transit delay and no curve number."""
    base = {
        "alpha": 0.6,
        "kc": 1.0,
        "impervious_fraction": 0.0,
        "bypass_fraction": 0.0,
        "transit_time_days": 0.0,
    }
    return SoilParameters(ru_mm=np.asarray(ru_mm, dtype=float), **(base | changes))


def empty_state() -> SoilState:
    return SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))


def wet_forcing(seed, n_days, n_columns, rain_scale=6.0, wet_share=0.45):
    """Gamma rain on a share of the days, uniform ETP (mm/day), capacities 20 to 300 mm."""
    rng = np.random.default_rng(seed)
    wet = rng.random((n_days, n_columns)) < wet_share
    precipitation = np.where(wet, rng.gamma(0.8, rain_scale, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(20.0, 300.0, n_columns)
    return precipitation, etp, ru_mm


def one_pulse(n_days, rain_mm):
    precipitation = np.zeros((n_days, 1))
    precipitation[0, 0] = rain_mm
    return precipitation, np.zeros((n_days, 1))


def transit_pulse_closed_form(transit_time_days, n_days):
    # Linear reservoir of constant k fed 50 mm on day 0 and nothing after.
    k = transit_time_days
    a = 1.0 - np.exp(-1.0 / k)
    t = np.arange(n_days)
    return np.where(t == 0, 50.0 * (1.0 - k * a), 50.0 * k * a * a * np.exp(-(t - 1) / k))


# Runoff lag. L = n + f reads (1 - f) * shift(n) + f * shift(n + 1).


def test_half_day_lag_splits_a_pulse():
    series = np.zeros((10, 1))
    series[3, 0] = 8.0

    lagged = apply_runoff_lag(series, 2.5)

    assert lagged[5, 0] == pytest.approx(4.0)
    assert lagged[6, 0] == pytest.approx(4.0)
    assert np.all(np.delete(lagged[:, 0], [5, 6]) == 0.0)


def test_fractional_lag_conserves_the_total():
    series = np.random.default_rng(5).uniform(0.0, 10.0, size=(40, 3))
    series[-5:] = 0.0  # quiet last days, so nothing is pushed past the end

    lagged = apply_runoff_lag(series, 1.75)

    assert lagged.sum(axis=0) == pytest.approx(series.sum(axis=0))


def test_lag_loses_what_passes_the_run_end():
    series = np.zeros((10, 1))
    series[7, 0] = 12.0  # shifted by 2 it lands on day 9, by 3 it would land on day 10

    lagged = apply_runoff_lag(series, 2.5)

    assert lagged[-1, 0] == pytest.approx(6.0)
    assert lagged.sum() == pytest.approx(6.0)


def test_zero_lag_returns_the_series():
    series = np.array([[1.0, 2.0], [3.0, 4.0]])

    assert apply_runoff_lag(series, 0.0) is series


# Transit store.


@pytest.mark.parametrize("transit_time_days", TRANSIT_TIMES_DAYS)
def test_transit_store_impulse(transit_time_days):
    n_days = int(60 * transit_time_days) + 10
    transit_mm = np.zeros(1)
    outflow = np.empty(n_days)
    for t in range(n_days):
        inflow = np.array([50.0 if t == 0 else 0.0])
        day_outflow, transit_mm = route_linear_reservoir(inflow, transit_mm, transit_time_days)
        outflow[t] = day_outflow[0]

    expected = transit_pulse_closed_form(transit_time_days, n_days)
    assert np.max(np.abs(outflow - expected)) < tol(IMPULSE_TOL)
    assert abs(outflow.sum() - 50.0) < tol("soil_transit_store_impulse_volume")


@pytest.mark.parametrize("transit_time_days", TRANSIT_TIMES_DAYS)
def test_recharge_of_a_saturated_soil(transit_time_days):
    # A full soil passes the 50 mm pulse to the transit store untouched.
    n_days = int(60 * transit_time_days) + 10
    precipitation, etp = one_pulse(n_days, 50.0)
    params = soil_params([100.0], transit_time_days=transit_time_days)

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    expected = transit_pulse_closed_form(transit_time_days, n_days)
    assert np.max(np.abs(fluxes.recharge[:, 0] - expected)) < tol(IMPULSE_TOL)


# Daily order of operations.


def test_bypass_recharges_on_a_dry_soil():
    # S = 0, RU = 150, b = 0.2, P = 10: the by-passed 0.2 * 10 mm recharges on day 0.
    params = soil_params([150.0], bypass_fraction=0.2)

    _, day = soil_step(empty_state(), np.array([10.0]), np.array([0.0]), params)

    assert day.recharge[0] == pytest.approx(2.0, abs=1e-12)


def test_rain_falls_before_the_soil_evaporates():
    # S = 0, RU = 100, alpha = 0.5, P = 10, ETP = 4: W = 10 before ETR, so
    # ETR = min(10, 4 * min(1, 10 / 50)) = 0.8. Evaporating first would give 0.
    params = soil_params([100.0], alpha=0.5)

    _, day = soil_step(empty_state(), np.array([10.0]), np.array([4.0]), params)

    assert day.etr[0] == pytest.approx(0.8, abs=1e-15)


# Spin-up.


def test_spinup_that_cannot_settle():
    # 300 mm of rain against 900 mm of ETP a year on a 1000 mm soil keeps draining it.
    precipitation = np.full((365, 1), 300.0 / 365)
    etp = np.full((365, 1), 900.0 / 365)

    spinup = spinup_state(precipitation, etp, soil_params([1000.0]), max_cycles=3)

    assert spinup.settled is False
    assert spinup.cycles == 3


def test_spinup_settles_when_winter_refills_the_soil():
    day = np.arange(365)
    is_winter = (day < 90) | (day >= 270)
    precipitation = np.broadcast_to(np.where(is_winter, 5.0, 0.0)[:, np.newaxis], (365, 5)).copy()
    etp = np.broadcast_to(np.where(is_winter, 0.0, 3.0)[:, np.newaxis], (365, 5)).copy()
    params = soil_params([50.0, 100.0, 150.0, 200.0, 250.0])

    spinup = spinup_state(precipitation, etp, params)

    assert spinup.settled is True
    assert spinup.cycles <= 3
    assert spinup.last_change_mm < tol("soil_spin_up_settling")


# Annual budget.


def test_annual_budget_sums_each_year():
    rng = np.random.default_rng(6)
    n_columns = 4
    years = np.concatenate([np.full(365, 2015), np.full(100, 2016)])  # second year cut short
    precipitation = rng.gamma(1.0, 4.0, (465, n_columns))
    etp = rng.uniform(0.0, 5.0, (465, n_columns))
    params = soil_params(rng.uniform(20.0, 200.0, n_columns), transit_time_days=3.0)
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    weights = np.full(n_columns, 1.0 / n_columns)

    budget = annual_budget(years, precipitation, etp, fluxes, weights)

    assert np.array_equal(budget.years, [2015, 2016])
    assert np.array_equal(budget.days, [365, 100])
    np.testing.assert_allclose(budget.precipitation[0], precipitation[:365].sum(axis=0), atol=1e-12)
    np.testing.assert_allclose(budget.precipitation[1], precipitation[365:].sum(axis=0), atol=1e-12)
    np.testing.assert_allclose(budget.etr[0], fluxes.etr[:365].sum(axis=0), atol=1e-12)
    np.testing.assert_allclose(budget.recharge[1], fluxes.recharge[365:].sum(axis=0), atol=1e-12)
    np.testing.assert_allclose(budget.basin("recharge"), budget.recharge @ weights, atol=1e-12)


# Water balance. P = etr + recharge + runoff + storage changes, to float64 precision.

PLAIN_SETS = [
    pytest.param(
        {"alpha": 0.6, "kc": 1.0, "impervious_fraction": 0.0, "bypass_fraction": 0.0},
        0.0,
        id="plain",
    ),
    pytest.param(
        {"alpha": 0.5, "kc": 1.2, "impervious_fraction": 0.2, "bypass_fraction": 0.1},
        5.0,
        id="sealed and by-pass",
    ),
    pytest.param(
        {"alpha": 1.0, "kc": 0.0, "impervious_fraction": 0.3, "bypass_fraction": 0.0},
        30.0,
        id="no evaporation",
    ),
    pytest.param(
        {"alpha": 0.6, "kc": 1.0, "impervious_fraction": 0.0, "bypass_fraction": 0.0},
        0.2,
        id="short transit",
    ),
]


@pytest.mark.parametrize(("changes", "transit_time_days"), PLAIN_SETS)
def test_balance_closes_over_ten_years(changes, transit_time_days):
    # 100 columns, the first three with zero capacity, with a seasonal ETP.
    rng = np.random.default_rng(0)
    n_days, n_columns = 3650, 100
    wet = rng.random((n_days, n_columns)) < 0.45
    precipitation = np.where(wet, rng.gamma(0.8, 6.0, (n_days, n_columns)), 0.0)
    day_of_year = np.arange(n_days) % 365
    seasonal_etp = np.clip(2.0 + 1.8 * np.sin(2 * np.pi * (day_of_year - 100) / 365), 0.0, None)
    etp = np.broadcast_to(seasonal_etp[:, np.newaxis], (n_days, n_columns)).copy()
    ru_mm = rng.uniform(0.0, 300.0, n_columns)
    ru_mm[:3] = 0.0
    params = soil_params(ru_mm, transit_time_days=transit_time_days, **changes)

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    residual = balance_residual(precipitation, fluxes)

    cumulative_relative = np.max(np.abs(residual.sum(axis=0)) / precipitation.sum(axis=0))
    daily_relative = np.max(np.abs(residual)) / precipitation.max()
    assert cumulative_relative < tol("soil_reservoir_kernel_balance")
    assert daily_relative < tol("soil_reservoir_kernel_balance")


# Curve number runoff routing and lag: the stores must enter the residual, daily and yearly.
ROUTED_SETS = [
    pytest.param(
        2,
        {"transit_time_days": 2.0, "curve_number": 70.0, "runoff_time_days": 0.0},
        id="routing, no delay",
    ),
    pytest.param(
        2,
        {
            "impervious_fraction": 0.05,
            "bypass_fraction": 0.1,
            "transit_time_days": 5.0,
            "curve_number": 80.0,
            "runoff_time_days": 1.0,
        },
        id="routing, 1 day",
    ),
    pytest.param(
        2,
        {
            "alpha": 0.5,
            "kc": 1.2,
            "curve_number": 90.0,
            "runoff_time_days": 3.5,
        },
        id="routing, 3.5 days",
    ),
    pytest.param(
        6,
        {"transit_time_days": 2.0, "curve_number": 70.0, "runoff_lag_days": 0.0},
        id="lag zero",
    ),
    pytest.param(
        6,
        {
            "impervious_fraction": 0.05,
            "bypass_fraction": 0.1,
            "transit_time_days": 5.0,
            "curve_number": 80.0,
            "runoff_time_days": 1.0,
            "runoff_lag_days": 0.75,
        },
        id="lag 0.75 day",
    ),
    pytest.param(
        6,
        {
            "alpha": 0.5,
            "kc": 1.2,
            "curve_number": 90.0,
            "runoff_time_days": 3.5,
            "runoff_lag_days": 4.0,
        },
        id="lag 4 days",
    ),
]


@pytest.mark.parametrize(("seed", "changes"), ROUTED_SETS)
def test_balance_closes_with_routing_and_lag(seed, changes):
    n_days = 3 * 365
    precipitation, etp, ru_mm = wet_forcing(seed, n_days, 15, rain_scale=8.0)
    years = 2020 + (np.arange(n_days) // 365)
    weights = np.full(15, 1.0 / 15)
    tolerance = tol("soil_curve_number_runoff_balance_with_routing")
    params = soil_params(ru_mm, **changes)

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    daily_residual = balance_residual(precipitation, fluxes)
    budget = annual_budget(years, precipitation, etp, fluxes, weights)

    assert np.max(np.abs(daily_residual)) / precipitation.max() < tolerance
    safe_rain = np.maximum(budget.precipitation, 1e-12)
    assert np.max(np.abs(budget.residual) / safe_rain) < tolerance
    # The stored closure must count every store, the lag's delay line included.
    storage_change = (
        budget.soil_storage_change
        + budget.transit_storage_change
        + budget.cn_storage_change
        + budget.lag_storage_change
    )
    displayed = budget.precipitation - budget.etr - budget.recharge - budget.runoff - storage_change
    assert np.max(np.abs(displayed - budget.residual) / safe_rain) < tolerance


def test_lag_moves_runoff_to_later_years_without_loss():
    precipitation, etp, ru_mm = wet_forcing(6, 3 * 365, 15, rain_scale=8.0)
    weights = np.full(15, 1.0 / 15)
    runs = {}
    for lag_days in (0.0, 2.0):
        params = soil_params(
            ru_mm, curve_number=80.0, runoff_time_days=1.0, runoff_lag_days=lag_days
        )
        runs[lag_days] = run_soil_balance(precipitation, etp, params, full_soil(params))

    total_unlagged = float((runs[0.0].runoff_cn @ weights).sum())
    total_lagged = float((runs[2.0].runoff_cn @ weights).sum())
    pushed_past_the_end = float(runs[2.0].lag_storage[-1] @ weights)

    assert total_lagged + pushed_past_the_end == pytest.approx(total_unlagged, rel=1e-9)


# Curve-number runoff. w = soil_mm / ru_mm interpolates the retention between S(CN1) (dry)
# and S(CN3) (full), and each extreme is the SCS-CN formula (HELP eq. 21, NEH-630 eq. 10-1).
CN = 80.0
RETENTION_DRY_MM = 25400.0 / (4.2 * CN / (10.0 - 0.058 * CN)) - 254.0
RETENTION_FULL_MM = 25400.0 / (23.0 * CN / (10.0 + 0.13 * CN)) - 254.0


def scs_runoff(rain_mm, retention_mm):
    excess = rain_mm - 0.2 * retention_mm
    return 0.0 if excess <= 0 else excess * excess / (excess + retention_mm)


def cn_soil(ru_mm, curve_number=CN):
    return soil_params([ru_mm], alpha=1.0, kc=0.0, curve_number=curve_number, runoff_time_days=0.0)


CN_RUNOFF = [
    pytest.param(0.0, 0.2 * RETENTION_DRY_MM - 1.0, 0.0, id="dry soil below the threshold"),
    pytest.param(0.0, 50.0, scs_runoff(50.0, RETENTION_DRY_MM), id="dry soil above it"),
    pytest.param(200.0, 50.0, scs_runoff(50.0, RETENTION_FULL_MM), id="full soil"),
]


@pytest.mark.parametrize(("soil_mm", "rain_mm", "runoff_mm"), CN_RUNOFF)
def test_curve_number_runoff(soil_mm, rain_mm, runoff_mm):
    state = SoilState(soil_mm=np.array([soil_mm]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([rain_mm]), np.array([0.0]), cn_soil(200.0))

    np.testing.assert_allclose(day.runoff_cn[0], runoff_mm, rtol=1e-12, atol=1e-12)


def test_zero_capacity_reads_as_a_full_soil():
    _, day = soil_step(empty_state(), np.array([50.0]), np.array([0.0]), cn_soil(0.0))

    assert np.isfinite(day.runoff_cn[0])
    assert day.runoff_cn[0] == pytest.approx(scs_runoff(50.0, RETENTION_FULL_MM), rel=1e-12)


# runoff_time routes the curve-number runoff without changing its volume.


def routed_run(runoff_time_days, n_days):
    precipitation, etp = one_pulse(n_days, 40.0)
    params = soil_params([150.0], curve_number=85.0, runoff_time_days=runoff_time_days)
    return run_soil_balance(precipitation, etp, params, full_soil(params))


def test_runoff_time_delays_and_smooths_a_pulse():
    immediate = routed_run(0.0, 60)
    routed = routed_run(5.0, 60)

    assert routed.runoff_cn[0, 0] < immediate.runoff_cn[0, 0]
    assert np.any(routed.runoff_cn[1:, 0] > 0.0)
    peak = int(np.argmax(routed.runoff_cn[:, 0]))
    assert peak in (0, 1)
    assert np.all(np.diff(routed.runoff_cn[peak:, 0]) <= 0.0)
    # What is delivered plus what the store still holds is the raw total.
    remaining = float(routed.end.cn_storage_mm[0])
    assert routed.runoff_cn[:, 0].sum() + remaining == pytest.approx(
        immediate.runoff_cn[:, 0].sum(), abs=1e-9
    )


def test_wider_time_constant_spreads_the_pulse():
    short = routed_run(2.0, 90)
    long = routed_run(8.0, 90)

    assert long.runoff_cn[0, 0] < short.runoff_cn[0, 0]
    long_total = long.runoff_cn[:, 0].sum() + float(long.end.cn_storage_mm[0])
    short_total = short.runoff_cn[:, 0].sum() + float(short.end.cn_storage_mm[0])
    assert long_total == pytest.approx(short_total, abs=1e-9)

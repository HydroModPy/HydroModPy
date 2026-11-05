from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
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

# A fractional ``runoff_lag`` interpolates between whole-day shifts.
#
# ``L = n + f`` reads ``(1 - f) * shift(n) + f * shift(n + 1)``. Away from the
# run's edges the delayed series carries the same total as the one it delays;
# only what a lag pushes past the last day is missing from it.


def test_a_half_day_lag_splits_a_single_pulse_over_its_two_neighbouring_days() -> None:
    series = np.zeros((10, 1))
    series[3, 0] = 8.0

    lagged = apply_runoff_lag(series, 2.5)

    assert lagged[5, 0] == pytest.approx(4.0)
    assert lagged[6, 0] == pytest.approx(4.0)
    assert np.all(np.delete(lagged[:, 0], [5, 6]) == 0.0)


def test_a_fractional_lag_conserves_the_total_when_nothing_reaches_the_run_end() -> None:
    rng = np.random.default_rng(5)
    series = rng.uniform(0.0, 10.0, size=(40, 3))
    series[-5:] = 0.0  # keep the last days quiet so nothing is pushed past the end

    lagged = apply_runoff_lag(series, 1.75)

    assert lagged.sum(axis=0) == pytest.approx(series.sum(axis=0))


def test_a_fractional_lag_loses_exactly_the_share_pushed_past_the_run_end() -> None:
    n_days = 10
    series = np.zeros((n_days, 1))
    series[7, 0] = 12.0  # shifted by 2 it still lands on the last day; by 3 it does not
    lag_days = 2.5

    lagged = apply_runoff_lag(series, lag_days)

    # Only the "shift by 2" half of the interpolation survives inside the run
    # (day 9); the "shift by 3" half would land on day 10, past the last day.
    assert lagged[-1, 0] == pytest.approx(6.0)
    assert lagged.sum() == pytest.approx(6.0)
    assert series.sum() - lagged.sum() == pytest.approx(6.0)


# A soil of zero capacity holds no water: it evaporates then passes the rest through.
#
# Section 7 fixes the evaporation ratio to 1 at the ``ru = 0`` limit (the
# prototype's choice), so the soil never stores anything and what the ETR
# leaves goes straight to the recharge.


def test_a_soil_with_no_capacity_passes_the_rain_through() -> None:
    rng = np.random.default_rng(1)
    n_days, n_columns = 50, 4
    precipitation = rng.gamma(1.0, 5.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=np.zeros(n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.all(fluxes.soil_storage == 0.0)
    assert np.max(np.abs(fluxes.recharge - (precipitation - fluxes.etr))) < 1e-12


# A soil whose yearly demand outruns its yearly rain never settles: it says so.
#
# ``ru = 1000`` mm, 300 mm of rain and 900 mm of ETP spread evenly over the
# year: the soil keeps draining every cycle instead of repeating, so
# `spinup_state` runs out its `max_cycles` budget with `settled = False`.


def test_a_spinup_that_cannot_settle_says_so() -> None:
    n_days, n_columns = 365, 1
    precipitation = np.full((n_days, n_columns), 300.0 / n_days)
    etp = np.full((n_days, n_columns), 900.0 / n_days)
    params = SoilParameters(
        ru_mm=np.array([1000.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    spinup = spinup_state(precipitation, etp, params, max_cycles=3)

    assert spinup.settled is False
    assert spinup.cycles == 3


# A crop coefficient of zero shuts the ETR off entirely.
#
# ``kc = 0`` makes the demand ``D = kc * ETP`` zero regardless of ETP, alpha or
# ru, so nothing evaporates and the ETP the soil left unmet equals the ETP that
# was loaded.


def test_a_zero_crop_coefficient_evaporates_nothing() -> None:
    rng = np.random.default_rng(2)
    n_days, n_columns = 30, 5
    precipitation = rng.gamma(1.0, 5.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(10.0, 200.0, n_columns),
        alpha=0.6,
        kc=0.0,
        impervious_fraction=0.1,
        bypass_fraction=0.05,
        transit_time_days=3.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.all(fluxes.etr == 0.0)
    assert np.all(fluxes.residual_etp == 0.0)


# A 50 mm pulse through the transit store follows the closed-form exponential reservoir.
#
# Section 7 gives the closed form for a linear reservoir of constant ``k`` fed
# one pulse and nothing after: ``Q(0) = 50(1 - k a)``,
# ``Q(t>=1) = 50 k a^2 exp(-(t-1)/k)`` with ``a = 1 - exp(-1/k)``. Checked
# directly on ``route_linear_reservoir`` and through the full soil balance with
# a saturated soil, so the pulse crosses it untouched.


_TRANSIT_TIMES_DAYS = (0.5, 2.0, 5.0, 20.0, 30.0)


def _closed_form(transit_time_days: float, n_days: int) -> np.ndarray:
    k = transit_time_days
    a = 1.0 - np.exp(-1.0 / k)
    t = np.arange(n_days)
    return np.where(t == 0, 50.0 * (1.0 - k * a), 50.0 * k * a * a * np.exp(-(t - 1) / k))


@pytest.mark.parametrize("transit_time_days", _TRANSIT_TIMES_DAYS)
def test_route_linear_reservoir_matches_the_exponential_reservoir(
    transit_time_days: float,
) -> None:
    n_days = int(60 * transit_time_days) + 10
    transit_mm = np.zeros(1)
    outflow = np.empty(n_days)
    for t in range(n_days):
        inflow = np.array([50.0 if t == 0 else 0.0])
        day_outflow, transit_mm = route_linear_reservoir(inflow, transit_mm, transit_time_days)
        outflow[t] = day_outflow[0]

    expected = _closed_form(transit_time_days, n_days)
    max_error = tol(
        "soil_transit_store_impulse__max_absolute_error_against_q_0_50_1_k_a_q_t_1_50_k_a_2_exp_t_1_k_mm"
    )
    volume_error = tol("soil_transit_store_impulse_volume")
    assert np.max(np.abs(outflow - expected)) < max_error
    assert abs(outflow.sum() - 50.0) < volume_error


@pytest.mark.parametrize("transit_time_days", _TRANSIT_TIMES_DAYS)
def test_run_soil_balance_routes_the_impulse_the_same_way(transit_time_days: float) -> None:
    n_days = int(60 * transit_time_days) + 10
    precipitation = np.zeros((n_days, 1))
    precipitation[0, 0] = 50.0
    etp = np.zeros((n_days, 1))
    params = SoilParameters(
        ru_mm=np.array([100.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=transit_time_days,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    expected = _closed_form(transit_time_days, n_days)
    max_error = tol(
        "soil_transit_store_impulse__max_absolute_error_against_q_0_50_1_k_a_q_t_1_50_k_a_2_exp_t_1_k_mm"
    )
    assert np.max(np.abs(fluxes.recharge[:, 0] - expected)) < max_error


# With no transit delay, a rain pulse above the soil capacity leaves the same day.
#
# ``transit_time_days = 0`` is the special case of section 7 where the linear
# reservoir is skipped: what overflows the soil reaches the recharge without a
# tail.


def test_an_impulse_without_transit_time_recharges_the_same_day() -> None:
    precipitation = np.array([[50.0], [0.0], [0.0], [0.0], [0.0]])
    etp = np.zeros_like(precipitation)
    params = SoilParameters(
        ru_mm=np.array([100.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.array_equal(fluxes.recharge[:, 0], [50.0, 0.0, 0.0, 0.0, 0.0])


# An integer ``runoff_lag`` shifts the routed runoff series by whole days.
#
# ``apply_runoff_lag`` is the pure delay applied after the ``runoff_time``
# reservoir. At an integer lag it is a plain shift: day ``t`` reads what day
# ``t - n`` held, with zero (no history) or the supplied history before day 0.


def test_a_three_day_lag_shifts_a_random_series_without_history() -> None:
    rng = np.random.default_rng(4)
    series = rng.uniform(0.0, 10.0, size=(30, 5))

    lagged = apply_runoff_lag(series, 3.0)

    assert np.array_equal(lagged[3:], series[:-3])
    assert np.all(lagged[:3] == 0.0)


def test_a_one_day_lag_reads_the_supplied_history_before_day_zero() -> None:
    series = np.zeros((5, 1))
    history = np.array([[1.0], [2.0], [3.0]])  # days -3, -2, -1

    lagged = apply_runoff_lag(series, 1.0, history_mm=history)

    # day 0 reads day -1 of the history (3.0); the rest is still zero.
    assert lagged[0, 0] == 3.0
    assert np.all(lagged[1:, 0] == 0.0)


def test_a_lag_longer_than_the_available_history_reads_zero_for_the_missing_days() -> None:
    series = np.zeros((3, 1))
    history = np.array([[5.0]])  # only day -1 is known

    lagged = apply_runoff_lag(series, 2.0, history_mm=history)

    # day 0 reads day -2, unknown: zero. Day 1 reads day -1: 5.0.
    assert lagged[0, 0] == 0.0
    assert lagged[1, 0] == 5.0


def test_a_zero_lag_returns_the_series_unchanged() -> None:
    series = np.array([[1.0, 2.0], [3.0, 4.0]])

    lagged = apply_runoff_lag(series, 0.0)

    assert lagged is series


# ``curve_number = None`` is bit-identical to the kernel before this feature.
#
# The curve-number term and its routing reservoir must cost nothing when the
# field is off: ``q_cn`` is exactly zero every day, so every other quantity
# follows the same float64 operations as before, down to the bit.


_PARAMETER_SETS = (
    (0.6, 1.0, 0.0, 0.0, 0.0),
    (0.5, 1.2, 0.2, 0.1, 5.0),
    (1.0, 0.0, 0.3, 0.0, 30.0),
)


def _synthetic_forcing() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(1)
    n_days, n_columns = 1000, 20
    wet = rng.random((n_days, n_columns)) < 0.4
    precipitation = np.where(wet, rng.gamma(0.8, 6.0, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(0.0, 300.0, n_columns)
    ru_mm[:2] = 0.0
    return precipitation, etp, ru_mm


def test_curve_number_none_is_bit_identical_to_the_kernel_without_it() -> None:
    precipitation, etp, ru_mm = _synthetic_forcing()

    for alpha, kc, impervious_fraction, bypass_fraction, transit_time_days in _PARAMETER_SETS:
        params_without_field = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
        )
        params_with_default_runoff_time = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=None,
            runoff_time_days=3.5,
        )

        before = run_soil_balance(
            precipitation, etp, params_without_field, full_soil(params_without_field)
        )
        after = run_soil_balance(
            precipitation,
            etp,
            params_with_default_runoff_time,
            full_soil(params_with_default_runoff_time),
        )

        assert np.array_equal(before.etr, after.etr)
        assert np.array_equal(before.residual_etp, after.residual_etp)
        assert np.array_equal(before.recharge, after.recharge)
        assert np.array_equal(before.runoff, after.runoff)
        assert np.array_equal(before.soil_storage, after.soil_storage)
        assert np.array_equal(before.transit_storage, after.transit_storage)
        assert np.all(after.runoff_cn == 0.0)


# With no rain at all, nothing runs off and nothing recharges: the soil only dries.
#
# ``impervious_fraction * 0 = 0`` and a soil that starts at or below ``ru``
# never crosses it without rain, so the storage only falls as the ETR draws it
# down.


def test_no_rain_recharges_nothing() -> None:
    rng = np.random.default_rng(3)
    n_days, n_columns = 60, 5
    precipitation = np.zeros((n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(10.0, 200.0, n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.2,
        bypass_fraction=0.1,
        transit_time_days=5.0,
    )
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.all(fluxes.recharge == 0.0)
    assert np.all(fluxes.runoff == 0.0)
    storage = np.concatenate(
        [fluxes.soil_storage_start[np.newaxis, :], fluxes.soil_storage], axis=0
    )
    assert np.all(np.diff(storage, axis=0) <= 0.0)


# Calling `soil_step` one day at a time reproduces `run_soil_balance` exactly.
#
# `run_soil_balance` is documented to only call `soil_step` in a loop: this
# pins that contract so the two never drift apart.


def test_one_step_at_a_time_gives_the_whole_run() -> None:
    rng = np.random.default_rng(5)
    n_days, n_columns = 40, 6
    precipitation = rng.gamma(1.0, 4.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(20.0, 200.0, n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.1,
        bypass_fraction=0.05,
        transit_time_days=4.0,
    )
    initial = full_soil(params)

    fluxes = run_soil_balance(precipitation, etp, params, initial)

    state = initial
    etr = np.empty((n_days, n_columns))
    residual_etp = np.empty((n_days, n_columns))
    recharge = np.empty((n_days, n_columns))
    runoff = np.empty((n_days, n_columns))
    for t in range(n_days):
        state, day = soil_step(state, precipitation[t], etp[t], params)
        etr[t] = day.etr
        residual_etp[t] = day.residual_etp
        recharge[t] = day.recharge
        runoff[t] = day.runoff

    assert np.array_equal(fluxes.etr, etr)
    assert np.array_equal(fluxes.residual_etp, residual_etp)
    assert np.array_equal(fluxes.recharge, recharge)
    assert np.array_equal(fluxes.runoff, runoff)
    assert np.array_equal(fluxes.end.soil_mm, state.soil_mm)
    assert np.array_equal(fluxes.end.transit_mm, state.transit_mm)


# ``runoff_lag = 0`` is bit-identical to the kernel before this feature.
#
# Mirrors ``test_curve_number_off_reproduces_the_kernel_bit_for_bit.py``: the
# lag must cost nothing when it is zero, whether the field is left at its
# default or set to 0.0 explicitly, with the curve-number routing active so the
# series it would delay is not itself empty.


_PARAMETER_SETS_2 = (
    (0.6, 1.0, 0.0, 0.0, 0.0, 75.0, 0.0),
    (0.5, 1.2, 0.2, 0.1, 5.0, 85.0, 2.0),
    (1.0, 0.0, 0.3, 0.0, 30.0, 90.0, 3.5),
)


def _synthetic_forcing_2() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(3)
    n_days, n_columns = 500, 12
    wet = rng.random((n_days, n_columns)) < 0.4
    precipitation = np.where(wet, rng.gamma(0.8, 6.0, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(20.0, 300.0, n_columns)
    return precipitation, etp, ru_mm


def test_runoff_lag_left_at_its_default_matches_setting_it_to_zero() -> None:
    precipitation, etp, ru_mm = _synthetic_forcing_2()

    for (
        alpha,
        kc,
        impervious_fraction,
        bypass_fraction,
        transit_time_days,
        curve_number,
        runoff_time_days,
    ) in _PARAMETER_SETS_2:
        params_default = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=curve_number,
            runoff_time_days=runoff_time_days,
        )
        params_explicit_zero = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=curve_number,
            runoff_time_days=runoff_time_days,
            runoff_lag_days=0.0,
        )

        before = run_soil_balance(precipitation, etp, params_default, full_soil(params_default))
        after = run_soil_balance(
            precipitation, etp, params_explicit_zero, full_soil(params_explicit_zero)
        )

        assert np.array_equal(before.etr, after.etr)
        assert np.array_equal(before.recharge, after.recharge)
        assert np.array_equal(before.runoff, after.runoff)
        assert np.array_equal(before.runoff_cn, after.runoff_cn)
        assert np.array_equal(before.cn_storage, after.cn_storage)
        assert np.all(after.lag_storage == 0.0)
        assert np.all(after.lag_storage_start == 0.0)


# The annual budget sums each calendar year's days, partial years included.
#
# Two years back to back, the second cut short, check that `annual_budget`
# sums exactly the days of each year and that `basin()` applies the declared
# weights.


def test_the_annual_budget_sums_the_days_of_each_year() -> None:
    rng = np.random.default_rng(6)
    n_columns = 4
    days_year_one, days_year_two = 365, 100
    n_days = days_year_one + days_year_two
    years = np.concatenate([np.full(days_year_one, 2015), np.full(days_year_two, 2016)])
    precipitation = rng.gamma(1.0, 4.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    params = SoilParameters(
        ru_mm=rng.uniform(20.0, 200.0, n_columns),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=3.0,
    )
    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
    weights = np.full(n_columns, 1.0 / n_columns)

    budget = annual_budget(years, precipitation, etp, fluxes, weights)

    assert np.array_equal(budget.years, [2015, 2016])
    assert np.array_equal(budget.days, [365, 100])
    assert np.allclose(budget.precipitation[0], precipitation[:365].sum(axis=0), atol=1e-12)
    assert np.allclose(budget.precipitation[1], precipitation[365:].sum(axis=0), atol=1e-12)
    assert np.allclose(budget.etr[0], fluxes.etr[:365].sum(axis=0), atol=1e-12)
    assert np.allclose(budget.recharge[1], fluxes.recharge[365:].sum(axis=0), atol=1e-12)

    basin_recharge = budget.basin("recharge")
    assert np.allclose(basin_recharge, budget.recharge @ weights, atol=1e-12)


# The by-pass reaches the recharge the same day, whether the soil is dry or not.
#
# With ``S = 0``, ``RU = 150``, ``b = 0.2`` and ``P = 10``: the by-passed share
# ``0.2 * 10 = 2`` mm never enters the soil bucket, so it recharges on day 0
# even though the dry soil absorbs the rest.


def test_the_bypass_reaches_the_recharge_on_a_dry_soil() -> None:
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))
    params = SoilParameters(
        ru_mm=np.array([150.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.2,
        transit_time_days=0.0,
    )

    _, day = soil_step(state, np.array([10.0]), np.array([0.0]), params)

    assert day.recharge[0] == pytest.approx(2.0, abs=1e-12)


# The water balance still closes once curve-number runoff and its routing join it.
#
# Mirrors ``test_the_soil_balance_closes_to_machine_precision.py``, with
# ``curve_number`` active and several ``runoff_time`` values: the new storage
# (``cn_storage``) has to enter ``balance_residual`` for the identity to hold,
# daily and summed over each calendar year.


_PARAMETER_SETS_3 = (
    (0.6, 1.0, 0.0, 0.0, 2.0, 70.0, 0.0),
    (0.6, 1.0, 0.05, 0.1, 5.0, 80.0, 1.0),
    (0.5, 1.2, 0.0, 0.0, 0.0, 90.0, 3.5),
)


def _synthetic_forcing_3() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(2)
    n_days, n_columns = 3 * 365, 15
    wet = rng.random((n_days, n_columns)) < 0.45
    precipitation = np.where(wet, rng.gamma(0.8, 8.0, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(20.0, 300.0, n_columns)
    years = 2020 + (np.arange(n_days) // 365)
    return precipitation, etp, ru_mm, years


def test_the_daily_and_annual_balance_close_to_1e_9_with_curve_number_routing() -> None:
    precipitation, etp, ru_mm, years = _synthetic_forcing_3()
    weights = np.full(ru_mm.shape[0], 1.0 / ru_mm.shape[0])
    tolerance = tol("soil_curve_number_runoff_balance_with_routing")

    for (
        alpha,
        kc,
        impervious_fraction,
        bypass_fraction,
        transit_time_days,
        curve_number,
        runoff_time_days,
    ) in _PARAMETER_SETS_3:
        params = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=curve_number,
            runoff_time_days=runoff_time_days,
        )
        fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
        daily_residual = balance_residual(precipitation, fluxes)

        daily_relative = np.max(np.abs(daily_residual)) / precipitation.max()
        assert daily_relative < tolerance

        budget = annual_budget(years, precipitation, etp, fluxes, weights)
        annual_relative = np.max(np.abs(budget.residual) / np.maximum(budget.precipitation, 1e-12))
        assert annual_relative < tolerance

        # The displayed/persisted closure (precipitation - ETR - recharge -
        # runoff - storage changes) must match the internal residual: the
        # curve-number routing store's storage change has to be counted too.
        displayed_storage_change = (
            budget.soil_storage_change + budget.transit_storage_change + budget.cn_storage_change
        )
        displayed_residual = (
            budget.precipitation
            - budget.etr
            - budget.recharge
            - budget.runoff
            - displayed_storage_change
        )
        displayed_relative = np.max(
            np.abs(displayed_residual - budget.residual) / np.maximum(budget.precipitation, 1e-12)
        )
        assert displayed_relative < tolerance


# The curve-number runoff reduces to its closed form at the two wetness extremes.
#
# ``w = soil_mm / ru_mm`` interpolates the retention between ``S(CN1)`` (dry
# soil, AMC I) and ``S(CN3)`` (full soil, AMC III). At each extreme the runoff
# is the plain SCS-CN formula with that single retention (HELP eq. 21,
# NEH-630 eq. 10-1).


_CN = 80.0


def _s1_s3(cn: float) -> tuple[float, float]:
    cn1 = 4.2 * cn / (10.0 - 0.058 * cn)
    cn3 = 23.0 * cn / (10.0 + 0.13 * cn)
    return 25400.0 / cn1 - 254.0, 25400.0 / cn3 - 254.0


def _closed_form_2(p: float, s: float) -> float:
    ia = 0.2 * s
    excess = p - ia
    return 0.0 if excess <= 0 else excess * excess / (excess + s)


def _params(curve_number: float | None = _CN) -> SoilParameters:
    return SoilParameters(
        ru_mm=np.array([200.0]),
        alpha=1.0,
        kc=0.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=curve_number,
        runoff_time_days=0.0,
    )


def test_a_dry_soil_below_its_retention_threshold_runs_off_nothing() -> None:
    s1, _ = _s1_s3(_CN)
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([0.2 * s1 - 1.0]), np.array([0.0]), _params())

    assert day.runoff_cn[0] == pytest.approx(0.0, abs=1e-12)


def test_a_dry_soil_above_the_threshold_matches_the_closed_form_with_s1() -> None:
    s1, _ = _s1_s3(_CN)
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([50.0]), np.array([0.0]), _params())

    assert day.runoff_cn[0] == pytest.approx(_closed_form_2(50.0, s1), rel=1e-12)


def test_a_full_soil_matches_the_closed_form_with_s3() -> None:
    _, s3 = _s1_s3(_CN)
    ru = 200.0
    state = SoilState(soil_mm=np.array([ru]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([50.0]), np.array([0.0]), _params())

    assert day.runoff_cn[0] == pytest.approx(_closed_form_2(50.0, s3), rel=1e-12)


def test_ru_zero_reads_as_a_full_soil_without_dividing_by_zero() -> None:
    _, s3 = _s1_s3(_CN)
    params = SoilParameters(
        ru_mm=np.array([0.0]),
        alpha=1.0,
        kc=0.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=_CN,
        runoff_time_days=0.0,
    )
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))

    _, day = soil_step(state, np.array([50.0]), np.array([0.0]), params)

    assert np.isfinite(day.runoff_cn[0])
    assert day.runoff_cn[0] == pytest.approx(_closed_form_2(50.0, s3), rel=1e-12)


# The day's rain reaches the soil before the ETR is computed on it.
#
# Order matters in section 7: with ``S = 0``, ``RU = 100``, ``alpha = 0.5``,
# ``P = 10`` and ``ETP = 4``, the wet soil is ``W = 10`` before ETR, so
# ``ETR = min(10, 4 * min(1, 10 / 50)) = 0.8``. Evaporating first, on the dry
# soil, would give zero instead.


def test_the_rain_falls_before_the_soil_evaporates() -> None:
    state = SoilState(soil_mm=np.array([0.0]), transit_mm=np.array([0.0]))
    params = SoilParameters(
        ru_mm=np.array([100.0]),
        alpha=0.5,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    _, day = soil_step(state, np.array([10.0]), np.array([4.0]), params)

    assert day.etr[0] == pytest.approx(0.8, abs=1e-15)


# ``runoff_time`` routes the curve-number runoff without changing its volume.
#
# ``runoff_time = 0`` sends ``Q_cn`` to the outlet the same day it falls,
# exactly as the unrouted term would. A longer time constant delays and
# smooths the same pulse through the exact linear-reservoir solution already
# used for the transit store (the discrete peak lands on the day after the
# pulse once ``k`` is not tiny, exactly as it does for the transit store), and
# the routed total plus what the reservoir still holds matches the raw total.


_CN_2 = 85.0


_RU = 150.0


def _params_2(runoff_time_days: float) -> SoilParameters:
    return SoilParameters(
        ru_mm=np.array([_RU]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=_CN_2,
        runoff_time_days=runoff_time_days,
    )


def _one_wet_day_forcing(n_days: int) -> tuple[np.ndarray, np.ndarray]:
    precipitation = np.zeros((n_days, 1))
    precipitation[0, 0] = 40.0
    etp = np.zeros((n_days, 1))
    return precipitation, etp


def test_runoff_time_zero_sends_the_runoff_the_same_day() -> None:
    precipitation, etp = _one_wet_day_forcing(5)
    params = _params_2(0.0)

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert fluxes.runoff_cn[0, 0] > 0.0
    assert np.all(fluxes.runoff_cn[1:, 0] == 0.0)


def test_a_longer_runoff_time_delays_and_smooths_the_same_pulse() -> None:
    n_days = 60
    precipitation, etp = _one_wet_day_forcing(n_days)

    immediate = run_soil_balance(precipitation, etp, _params_2(0.0), full_soil(_params_2(0.0)))
    routed = run_soil_balance(precipitation, etp, _params_2(5.0), full_soil(_params_2(5.0)))

    assert routed.runoff_cn[0, 0] < immediate.runoff_cn[0, 0]
    assert np.any(routed.runoff_cn[1:, 0] > 0.0)

    peak = int(np.argmax(routed.runoff_cn[:, 0]))
    assert peak in (0, 1)
    assert np.all(np.diff(routed.runoff_cn[peak:, 0]) <= 0.0)

    remaining = float(routed.end.cn_storage_mm[0])
    assert routed.runoff_cn[:, 0].sum() + remaining == pytest.approx(
        immediate.runoff_cn[:, 0].sum(), abs=1e-9
    )


def test_a_wider_time_constant_spreads_the_pulse_further() -> None:
    n_days = 90
    precipitation, etp = _one_wet_day_forcing(n_days)

    short = run_soil_balance(precipitation, etp, _params_2(2.0), full_soil(_params_2(2.0)))
    long = run_soil_balance(precipitation, etp, _params_2(8.0), full_soil(_params_2(8.0)))

    assert long.runoff_cn[0, 0] < short.runoff_cn[0, 0]

    short_remaining = float(short.end.cn_storage_mm[0])
    long_remaining = float(long.end.cn_storage_mm[0])
    assert long.runoff_cn[:, 0].sum() + long_remaining == pytest.approx(
        short.runoff_cn[:, 0].sum() + short_remaining, abs=1e-9
    )


# The sealed share of a column runs off at once; the soil only sees the rest.
#
# ``impervious_fraction`` weights every soil output by area: with ``f = 0.25``
# the runoff is exactly ``0.25 * P``, the ETR never exceeds ``0.75 * kc * ETP``,
# and what the soil could not evaporate on its unsealed share is the residual
# ETP.


def test_the_sealed_share_neither_infiltrates_nor_evaporates() -> None:
    rng = np.random.default_rng(4)
    n_days, n_columns = 40, 5
    precipitation = rng.gamma(1.0, 5.0, (n_days, n_columns))
    etp = rng.uniform(0.0, 4.0, (n_days, n_columns))
    kc = 1.2
    params = SoilParameters(
        ru_mm=rng.uniform(10.0, 200.0, n_columns),
        alpha=0.6,
        kc=kc,
        impervious_fraction=0.25,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))

    assert np.max(np.abs(fluxes.runoff - 0.25 * precipitation)) < 1e-12
    assert np.all(fluxes.etr <= 0.75 * kc * etp + 1e-12)
    assert np.max(np.abs(fluxes.residual_etp - 0.75 * (kc * etp - fluxes.etr / 0.75))) < 1e-12


# The soil reservoir closes its water balance to machine precision.
#
# Spec section 7 proves the identity ``P = etr + recharge + runoff +
# g*(S'-S) + g*(R'-R)`` term by term; this test measures how close float64
# arithmetic keeps that promise over a long run, four parameter sets, and
# columns of zero capacity.


_PARAMETER_SETS_4 = (
    (0.6, 1.0, 0.0, 0.0, 0.0),
    (0.5, 1.2, 0.2, 0.1, 5.0),
    (1.0, 0.0, 0.3, 0.0, 30.0),
    (0.6, 1.0, 0.0, 0.0, 0.2),
)


def _synthetic_forcing_4() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    n_days, n_columns = 3650, 100
    wet = rng.random((n_days, n_columns)) < 0.45
    precipitation = np.where(wet, rng.gamma(0.8, 6.0, (n_days, n_columns)), 0.0)
    day_of_year = np.arange(n_days) % 365
    seasonal_etp = np.clip(2.0 + 1.8 * np.sin(2 * np.pi * (day_of_year - 100) / 365), 0.0, None)
    etp = np.broadcast_to(seasonal_etp[:, np.newaxis], (n_days, n_columns)).copy()
    ru_mm = rng.uniform(0.0, 300.0, n_columns)
    ru_mm[:3] = 0.0
    return precipitation, etp, ru_mm


def test_the_balance_closes_to_machine_precision() -> None:
    precipitation, etp, ru_mm = _synthetic_forcing_4()
    worst_cumulative_relative = 0.0
    worst_daily_relative = 0.0

    for alpha, kc, impervious_fraction, bypass_fraction, transit_time_days in _PARAMETER_SETS_4:
        params = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
        )
        fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
        residual = balance_residual(precipitation, fluxes)

        cumulative_relative = np.max(np.abs(residual.sum(axis=0)) / precipitation.sum(axis=0))
        daily_relative = np.max(np.abs(residual)) / precipitation.max()
        worst_cumulative_relative = max(worst_cumulative_relative, cumulative_relative)
        worst_daily_relative = max(worst_daily_relative, daily_relative)

    tolerance = tol("soil_reservoir_kernel_balance")
    assert worst_cumulative_relative < tolerance
    assert worst_daily_relative < tolerance


# The water balance still closes once ``runoff_lag`` delays the routed runoff.
#
# Mirrors ``test_the_curve_number_balance_closes_with_routing.py``: the new
# ``lag_storage`` has to enter ``balance_residual`` for the identity to hold,
# daily and summed over each calendar year, exactly as ``cn_storage`` already
# does for ``runoff_time``.


_PARAMETER_SETS_5 = (
    (0.6, 1.0, 0.0, 0.0, 2.0, 70.0, 0.0, 0.0),
    (0.6, 1.0, 0.05, 0.1, 5.0, 80.0, 1.0, 0.75),
    (0.5, 1.2, 0.0, 0.0, 0.0, 90.0, 3.5, 4.0),
)


def _synthetic_forcing_5() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(6)
    n_days, n_columns = 3 * 365, 15
    wet = rng.random((n_days, n_columns)) < 0.45
    precipitation = np.where(wet, rng.gamma(0.8, 8.0, (n_days, n_columns)), 0.0)
    etp = rng.uniform(0.0, 5.0, (n_days, n_columns))
    ru_mm = rng.uniform(20.0, 300.0, n_columns)
    years = 2020 + (np.arange(n_days) // 365)
    return precipitation, etp, ru_mm, years


def test_the_daily_and_annual_balance_close_to_1e_9_with_a_runoff_lag() -> None:
    precipitation, etp, ru_mm, years = _synthetic_forcing_5()
    weights = np.full(ru_mm.shape[0], 1.0 / ru_mm.shape[0])
    tolerance = tol("soil_curve_number_runoff_balance_with_routing")

    for (
        alpha,
        kc,
        impervious_fraction,
        bypass_fraction,
        transit_time_days,
        curve_number,
        runoff_time_days,
        runoff_lag_days,
    ) in _PARAMETER_SETS_5:
        params = SoilParameters(
            ru_mm=ru_mm,
            alpha=alpha,
            kc=kc,
            impervious_fraction=impervious_fraction,
            bypass_fraction=bypass_fraction,
            transit_time_days=transit_time_days,
            curve_number=curve_number,
            runoff_time_days=runoff_time_days,
            runoff_lag_days=runoff_lag_days,
        )
        fluxes = run_soil_balance(precipitation, etp, params, full_soil(params))
        daily_residual = balance_residual(precipitation, fluxes)

        daily_relative = np.max(np.abs(daily_residual)) / precipitation.max()
        assert daily_relative < tolerance

        budget = annual_budget(years, precipitation, etp, fluxes, weights)
        annual_relative = np.max(np.abs(budget.residual) / np.maximum(budget.precipitation, 1e-12))
        assert annual_relative < tolerance

        # The displayed/persisted closure (precipitation - ETR - recharge -
        # runoff - storage changes) must match the internal residual: the
        # lag's own delay line has to be counted too.
        displayed_storage_change = (
            budget.soil_storage_change
            + budget.transit_storage_change
            + budget.cn_storage_change
            + budget.lag_storage_change
        )
        displayed_residual = (
            budget.precipitation
            - budget.etr
            - budget.recharge
            - budget.runoff
            - displayed_storage_change
        )
        displayed_relative = np.max(
            np.abs(displayed_residual - budget.residual) / np.maximum(budget.precipitation, 1e-12)
        )
        assert displayed_relative < tolerance


def test_a_runoff_lag_moves_volume_from_early_years_to_later_ones_without_losing_any() -> None:
    """Over the whole run, the lag's delay line starts and nets out near zero.

    Nothing pushed past the last day (the lag is short next to the run), so
    the total curve-number runoff delivered matches the undelayed total.
    """
    precipitation, etp, ru_mm, years = _synthetic_forcing_5()
    weights = np.full(ru_mm.shape[0], 1.0 / ru_mm.shape[0])

    params_unlagged = SoilParameters(
        ru_mm=ru_mm,
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=80.0,
        runoff_time_days=1.0,
        runoff_lag_days=0.0,
    )
    params_lagged = SoilParameters(
        ru_mm=ru_mm,
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
        curve_number=80.0,
        runoff_time_days=1.0,
        runoff_lag_days=2.0,
    )

    unlagged = run_soil_balance(precipitation, etp, params_unlagged, full_soil(params_unlagged))
    lagged = run_soil_balance(precipitation, etp, params_lagged, full_soil(params_lagged))

    total_unlagged = float((unlagged.runoff_cn @ weights).sum())
    total_lagged = float((lagged.runoff_cn @ weights).sum())
    pushed_past_the_end = float(lagged.lag_storage[-1] @ weights)

    assert total_lagged + pushed_past_the_end == pytest.approx(total_unlagged, rel=1e-9)


# A year whose winter rain always resaturates the soil settles in a few cycles.
#
# Heavy winter rain far above every column's capacity, and a dry summer that
# only draws the soil down, brings the end-of-year state back to the same
# saturated soil every cycle: `spinup_state` should settle quickly.


def test_the_spinup_settles_on_a_year_that_refills_the_soil() -> None:
    n_days, n_columns = 365, 5
    day = np.arange(n_days)
    is_winter = (day < 90) | (day >= 270)
    precipitation = np.where(is_winter, 5.0, 0.0)[:, np.newaxis]
    precipitation = np.broadcast_to(precipitation, (n_days, n_columns)).copy()
    etp = np.where(is_winter, 0.0, 3.0)[:, np.newaxis]
    etp = np.broadcast_to(etp, (n_days, n_columns)).copy()
    params = SoilParameters(
        ru_mm=np.array([50.0, 100.0, 150.0, 200.0, 250.0]),
        alpha=0.6,
        kc=1.0,
        impervious_fraction=0.0,
        bypass_fraction=0.0,
        transit_time_days=0.0,
    )

    spinup = spinup_state(precipitation, etp, params)

    assert spinup.settled is True
    assert spinup.cycles <= 3
    assert spinup.last_change_mm < tol("soil_spin_up_settling")

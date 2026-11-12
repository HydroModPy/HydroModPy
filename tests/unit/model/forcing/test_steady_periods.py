"""Rate of a steady period from a recharge record, in the unit of the record (here mm/day).

A steady period takes the time mean of the record, each value weighted by its period length,
so a short wet February weighs less than a long dry July. Without lengths each value counts once.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.forcing.steady_periods import (
    apply_first_clim,
    one_period_rate,
    split_net_recharge,
    steady_rate,
)

RATES = [1.0, 4.0, 2.0]
DAYS = np.array([31.0, 28.0, 31.0])
TIME_MEAN = (31.0 + 112.0 + 62.0) / 90.0  # (1 x 31 + 4 x 28 + 2 x 31) / 90 days
STEADY_FIRST = np.array([True, False, False])


def test_steady_rate_gives_the_volume_of_the_record():
    value = float(steady_rate(RATES, "mean", durations=DAYS))

    assert value == pytest.approx(TIME_MEAN)
    assert value * DAYS.sum() == pytest.approx(np.dot(RATES, DAYS))
    assert value != pytest.approx(np.mean(RATES), rel=1e-3)


def test_unit_of_the_lengths_does_not_matter():
    assert float(steady_rate(RATES, "mean", durations=DAYS * 86400.0)) == pytest.approx(TIME_MEAN)


def test_grid_takes_the_time_mean_cell_by_cell():
    rates = {0: np.array([1.0, 0.0]), 1: np.array([4.0, 1.0]), 2: np.array([2.0, 0.0])}

    out = apply_first_clim(rates, steady=STEADY_FIRST, first_clim="mean", durations=DAYS)

    np.testing.assert_allclose(out[0], [TIME_MEAN, 28.0 / 90.0])
    np.testing.assert_allclose(out[1], rates[1])


def test_net_rate_of_a_split_recharge_is_the_time_mean_of_the_net_rates():
    net = {0: -1.0, 1: 4.0, 2: -2.0}

    recharge, deficit = split_net_recharge(
        net, steady=STEADY_FIRST, first_clim="mean", durations=DAYS
    )

    expected = np.dot(list(net.values()), DAYS) / DAYS.sum()
    assert float(recharge[0]) - float(deficit[0]) == pytest.approx(expected)
    assert float(recharge[0]) == pytest.approx(4.0 * 28.0 / 90.0)


def test_record_without_lengths_counts_each_value_once():
    assert one_period_rate(RATES, steady=True, first_clim="mean") == pytest.approx(7.0 / 3.0)
    assert one_period_rate(RATES, steady=True, first_clim="first", durations=DAYS) == 1.0


REFUSALS = [
    pytest.param(
        steady_rate,
        (RATES, "mean"),
        {"durations": [31.0, 28.0]},
        "period length",
        id="one length short",
    ),
    pytest.param(
        steady_rate,
        (RATES, "mean"),
        {"durations": [31.0, 0.0, 31.0]},
        "period length",
        id="zero length",
    ),
    pytest.param(
        steady_rate,
        (RATES, "mean"),
        {"durations": [31.0, -1.0, 31.0]},
        "period length",
        id="negative length",
    ),
    pytest.param(
        steady_rate,
        (RATES, "mean"),
        {"durations": [31.0, np.nan, 31.0]},
        "period length",
        id="nan length",
    ),
    pytest.param(
        apply_first_clim,
        ({0: 1.0, 3: 2.0},),
        {"steady": [True], "first_clim": "mean", "durations": DAYS},
        "has no length",
        id="period beyond the lengths",
    ),
]


@pytest.mark.parametrize(("function", "args", "kwargs", "match"), REFUSALS)
def test_refusals(function, args, kwargs, match):
    with pytest.raises(ValueError, match=match):
        function(*args, **kwargs)

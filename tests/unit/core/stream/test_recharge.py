"""The mean recharge the stream-network criterion divides by.

R is the time mean over the periods, each weighted by its length, of the rate
the forcing gives each period, itself averaged over the cells by their area.
Whatever the weights, a mean stays between the smallest and largest rate.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.stream.recharge import (
    criterion_mean_recharge,
    forcing_period_rates,
    mean_recharge_m_s,
)

# ----------------------------------------------------------- period rates


def _daily(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


def test_a_period_rate_is_the_mean_of_the_samples_inside_it():
    edges = pd.to_datetime(["2020-01-01", "2020-01-03", "2020-01-05"])
    rates = forcing_period_rates(_daily([1, 3, 5, 7]), edges)
    assert rates.tolist() == [2.0, 6.0]


def test_a_period_without_sample_takes_the_last_sample_before_its_end():
    series = pd.Series([4.0], index=pd.to_datetime(["2020-01-01"]))
    edges = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-05"])
    # period 1 holds no sample: the last one before its end stands for it
    assert forcing_period_rates(series, edges).tolist() == [4.0, 4.0]


def test_a_period_before_any_sample_is_left_as_nan_for_the_caller_to_see():
    series = _daily([5.0, 5.0], start="2020-02-01")
    edges = pd.to_datetime(["2020-01-01", "2020-01-10", "2020-02-01", "2020-02-03"])
    rates = forcing_period_rates(series, edges)
    assert np.isnan(rates[:2]).all()
    assert rates[-1] == 5.0


def test_a_negative_rate_is_clipped_at_zero_as_the_recharge_package_receives_it():
    edges = pd.to_datetime(["2020-01-01", "2020-01-03", "2020-01-05"])
    rates = forcing_period_rates(_daily([-4, -2, 1, 3]), edges)
    assert rates.tolist() == [0.0, 2.0]
    assert (rates >= 0).all()


def test_a_run_needs_two_period_edges():
    with pytest.raises(ValueError, match="at least two period edges, got 1"):
        forcing_period_rates(_daily([1.0]), pd.to_datetime(["2020-01-01"]))


# ------------------------------------------------------------------ the mean


@pytest.mark.parametrize(
    ("values", "kwargs", "expected"),
    [
        (np.array([1.0, 2.0, 3.0]), {}, 2.0),
        ([1.0, 3.0], {}, 2.0),
        ([1.0, 3.0], {"durations": [3.0, 1.0]}, 1.5),
        ([np.array([1.0, 3.0]), np.array([5.0, 5.0])], {"areas": [3.0, 1.0]}, (1.5 + 5.0) / 2),
        ([np.array([1.0, 3.0]), 4.0], {"areas": [1.0, 1.0], "durations": [1.0, 2.0]}, 10.0 / 3),
        ([np.array([1.0, np.nan]), 3.0], {}, 2.0),
        ([np.array([1.0, 100.0]), np.array([3.0, 3.0])], {"areas": [1.0, 0.0]}, 2.0),
    ],
    ids=[
        "one-array-plain-mean",
        "list-of-periods",
        "weighted-by-length",
        "cells-weighted-by-area",
        "entry-not-sized-like-areas-takes-plain-mean",
        "non-finite-carries-no-weight",
        "zero-area-cell-ignored",
    ],
)
def test_the_mean_recharge_weighs_periods_by_length_and_cells_by_area(values, kwargs, expected):
    assert criterion_mean_recharge(values, **kwargs) == pytest.approx(expected)


@pytest.mark.parametrize("seed", range(4))
def test_the_mean_stays_between_the_smallest_and_largest_rate(seed):
    rng = np.random.default_rng(seed)
    periods = [rng.uniform(1e-9, 1e-8, size=6) for _ in range(5)]
    got = criterion_mean_recharge(
        periods, areas=rng.uniform(1, 100, 6), durations=rng.uniform(1, 40, 5)
    )
    flat = np.concatenate(periods)
    assert flat.min() <= got <= flat.max()


def test_a_uniform_recharge_is_its_own_mean_whatever_the_weights():
    periods = [np.full(4, 2e-9)] * 3
    got = criterion_mean_recharge(periods, areas=[1.0, 5.0, 2.0, 9.0], durations=[1, 2, 3])
    assert got == pytest.approx(2e-9)


@pytest.mark.parametrize(
    ("args", "kwargs", "match"),
    [
        ([1.0, 2.0], {"durations": [1.0]}, "2 recharge entries need 2 lengths"),
        ([np.nan, np.inf], {}, "holds no finite rate"),
        ([np.array([1.0, 2.0])], {"areas": [0.0, -1.0]}, "holds no finite rate"),
    ],
)
def test_a_recharge_without_a_usable_rate_or_length_is_refused(args, kwargs, match):
    with pytest.raises(ValueError, match=match):
        criterion_mean_recharge(args, **kwargs)


# ------------------------------------------------------------- built model


class _Mesh:
    def __init__(self, areas):
        self._areas = np.asarray(areas, dtype=float)

    def cell_areas(self):
        return self._areas


def _model(recharge, perlen=None, areas=None):
    model = SimpleNamespace(recharge=recharge, perlen=perlen)
    if areas is not None:
        model.solver_mesh = _Mesh(areas)
    return model


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # one value per period, weighted by period length
        (_model(np.array([1.0, 3.0]), perlen=[3.0, 1.0]), 1.5),
        # a list is one rate per period, whatever its length
        (_model([2.0, 4.0], perlen=[1.0, 1.0]), 3.0),
        # a payload sized like the cells stands for every period at once
        (_model(np.array([1.0, 3.0]), perlen=[1.0, 1.0], areas=[3.0, 1.0]), 1.5),
        # a table gives one entry per period it states
        (_model({0: 2.0, 2: 4.0}, perlen=[1.0, 5.0, 3.0]), (2.0 * 1 + 4.0 * 3) / 4),
        (_model({1: np.array([1.0, 3.0])}, perlen=[1.0, 2.0], areas=[1.0, 1.0]), 2.0),
        # a scalar record has no known length
        (_model(5.0), 5.0),
        (_model(np.array([[1.0, 3.0], [5.0, 7.0]]), perlen=[1.0, 1.0]), 4.0),
    ],
    ids=[
        "array-by-period",
        "list",
        "cell-payload",
        "table",
        "table-of-cells",
        "scalar",
        "2d-per-period",
    ],
)
def test_the_mean_recharge_is_read_back_from_what_the_built_model_holds(model, expected):
    assert mean_recharge_m_s(model) == pytest.approx(expected)


def test_a_model_without_recharge_has_no_denominator():
    with pytest.raises(ValueError, match="declares no recharge"):
        mean_recharge_m_s(SimpleNamespace())


def test_a_model_whose_recharge_is_not_finite_is_refused_with_the_user_message():
    with pytest.raises(ValueError, match="not a finite number"):
        mean_recharge_m_s(_model(np.array([np.nan, np.nan]), perlen=[1.0, 1.0]))

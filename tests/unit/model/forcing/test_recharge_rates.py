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

from hydromodpy.catchment.stream_network.geometry import RECHARGE_MOVE_TOLERANCE
from hydromodpy.model.forcing.recharge_rates import (
    criterion_mean_recharge,
    forcing_period_rates,
    mean_recharge_m_s,
)


def _daily(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


def test_empty_period_takes_last_sample():
    series = pd.Series([4.0], index=pd.to_datetime(["2020-01-01"]))
    edges = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-05"])
    # period 1 holds no sample: the last one before its end stands for it
    assert forcing_period_rates(series, edges).tolist() == [4.0, 4.0]


def test_period_before_samples_is_nan():
    series = _daily([5.0, 5.0], start="2020-02-01")
    edges = pd.to_datetime(["2020-01-01", "2020-01-10", "2020-02-01", "2020-02-03"])
    rates = forcing_period_rates(series, edges)
    assert np.isnan(rates[:2]).all()
    assert rates[-1] == 5.0


def test_two_period_edges_needed():
    with pytest.raises(ValueError, match="at least two period edges, got 1"):
        forcing_period_rates(_daily([1.0]), pd.to_datetime(["2020-01-01"]))


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
        ([1.0, np.nan, 3.0], {"durations": [1.0, 50.0, 3.0]}, 2.5),
    ],
    ids=[
        "one-array-plain-mean",
        "list-of-periods",
        "weighted-by-length",
        "cells-weighted-by-area",
        "entry-not-sized-like-areas-takes-plain-mean",
        "non-finite-carries-no-weight",
        "zero-area-cell-ignored",
        "period-without-finite-rate-loses-its-length",
    ],
)
def test_criterion_mean_weights(values, kwargs, expected):
    assert criterion_mean_recharge(values, **kwargs) == pytest.approx(expected)


def test_uniform_recharge_is_its_mean():
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
def test_criterion_mean_refusals(args, kwargs, match):
    with pytest.raises(ValueError, match=match):
        criterion_mean_recharge(args, **kwargs)


def _model(recharge, perlen=None, areas=None):
    model = SimpleNamespace(recharge=recharge, perlen=perlen)
    if areas is not None:
        model.solver_mesh = SimpleNamespace(cell_areas=lambda: np.asarray(areas, dtype=float))
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
        # periods of a grid weigh like its cells, by length (1 x 31 + 4 x 28 + 2 x 31) / 90 d
        (
            _model(
                {k: np.array([v, v]) for k, v in enumerate([1.0, 4.0, 2.0])},
                perlen=np.array([31.0, 28.0, 31.0]) * 86400.0,
                areas=[1.0, 3.0],
            ),
            (31.0 + 112.0 + 62.0) / 90.0,
        ),
        # a record the criterion cannot date counts each value once
        (_model([1.0, 4.0, 1.0]), 2.0),
        (_model([1.0, 4.0, 1.0], perlen=np.array([86400.0])), 2.0),
    ],
    ids=[
        "array-by-period",
        "list",
        "cell-payload",
        "table",
        "table-of-cells",
        "scalar",
        "2d-per-period",
        "grid-weighted-by-length",
        "undated-list",
        "one-length-for-three-rates",
    ],
)
def test_mean_recharge_of_model(model, expected):
    assert mean_recharge_m_s(model) == pytest.approx(expected)


def test_model_without_recharge_refused():
    with pytest.raises(ValueError, match="declares no recharge"):
        mean_recharge_m_s(SimpleNamespace())


def test_non_finite_recharge_refused():
    with pytest.raises(ValueError, match="not a finite number"):
        mean_recharge_m_s(_model(np.array([np.nan, np.nan]), perlen=[1.0, 1.0]))


MONTH_ENDS = pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
MONTH_RATES = np.array([2.0, 8.0, 1.0])
MONTH_TIME_MEAN = float(np.average(MONTH_RATES, weights=[31.0, 29.0, 31.0]))


def test_steady_and_monthly_agree():
    # The calibration by hand: a move here would log a change of data that never came.
    samples = pd.Series(MONTH_RATES, index=MONTH_ENDS)
    whole = pd.DatetimeIndex(["2000-01-01", "2000-04-01"])
    months = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])

    steady = criterion_mean_recharge(list(forcing_period_rates(samples, whole)))
    monthly = criterion_mean_recharge(
        list(forcing_period_rates(samples, months)),
        durations=(months[1:] - months[:-1]).total_seconds().to_numpy(),
    )

    assert np.isclose(steady, monthly, rtol=RECHARGE_MOVE_TOLERANCE, atol=0.0)
    assert steady == pytest.approx(MONTH_TIME_MEAN)

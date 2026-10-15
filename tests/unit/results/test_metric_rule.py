"""A metric is computed on the declared window only, and says how many samples it used."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.core import metrics as kernels
from hydromodpy.results.metric_rule import (
    METRIC_NAMES,
    METRIC_RULE_VERSION,
    DateWindow,
    MetricRule,
    MetricScore,
    score,
)

INDEX = pd.date_range("2015-01-01", "2016-12-31", freq="D")
WINDOW = DateWindow(start=date(2016, 1, 1), end=date(2016, 12, 31))
RULE = MetricRule(station="J0014010", window=WINDOW)


def _series(seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.uniform(0.5, 5.0, len(INDEX)), index=INDEX)


def test_nse_is_computed_on_the_declared_window_only():
    observed = _series(1)
    simulated = observed * 1.1
    # A spin-up year that disagrees wildly must not count.
    simulated[INDEX < "2016-01-01"] = 100.0

    result = score(simulated, observed, RULE, "nse")

    inside = INDEX >= "2016-01-01"
    expected = kernels.nse(simulated[inside].to_numpy(), observed[inside].to_numpy())
    assert result.value == pytest.approx(expected)
    assert result.value > 0.5
    assert (result.nse_window_start, result.nse_window_end) == (WINDOW.start, WINDOW.end)
    assert result.nse_n == 366
    assert result.metric_rule_version == METRIC_RULE_VERSION == "1"


def test_without_a_window_there_is_no_score():
    result = score(_series(1), _series(2), MetricRule(station="J0014010"), "nse")
    assert result == MetricScore(
        metric="nse",
        value=None,
        nse_window_start=None,
        nse_window_end=None,
        nse_n=0,
        metric_rule_version="1",
    )


def test_nse_n_counts_the_instants_both_series_carry_a_finite_value_at():
    observed = _series(1)
    simulated = observed.copy()
    observed[INDEX[-10:]] = np.nan
    simulated = simulated.drop(INDEX[366:371])

    result = score(simulated, observed, RULE, "nse")

    assert result.nse_n == 366 - 10 - 5
    assert result.value == pytest.approx(1.0)


def test_the_last_day_of_the_window_is_included():
    index = pd.date_range("2016-12-30 00:00", "2017-01-01 00:00", freq="6h")
    series = pd.Series(np.arange(len(index), dtype=float), index=index)
    rule = MetricRule(window=DateWindow(start=date(2016, 12, 31), end=date(2016, 12, 31)))

    assert score(series, series, rule, "rmse").nse_n == 4


def test_a_window_outside_the_data_gives_no_value_and_zero_samples():
    rule = MetricRule(window=DateWindow(start=date(2030, 1, 1), end=date(2030, 12, 31)))
    result = score(_series(1), _series(2), rule, "nse")
    assert result.value is None and result.nse_n == 0
    assert result.nse_window_start == date(2030, 1, 1)


def test_constant_observations_give_no_value_rather_than_nan():
    observed = pd.Series(1.0, index=INDEX)
    result = score(_series(1), observed, RULE, "nse")
    assert result.value is None and result.nse_n == 366


def test_a_timezone_aware_index_is_scored_on_its_own_days():
    index = pd.date_range("2016-01-01", "2016-01-10", freq="D", tz="UTC")
    series = pd.Series(np.arange(10, dtype=float), index=index)
    rule = MetricRule(window=DateWindow(start=date(2016, 1, 3), end=date(2016, 1, 5)))
    assert score(series, series, rule, "rmse").nse_n == 3


@pytest.mark.parametrize("metric", METRIC_NAMES)
def test_every_known_metric_scores_under_the_rule(metric):
    observed = _series(3)
    result = score(observed * 1.05, observed, RULE, metric)
    assert result.metric == metric
    assert result.value is not None
    assert result.nse_n == 366


def test_an_unknown_metric_is_refused_with_the_known_ones():
    with pytest.raises(ValueError, match="nse, kge, rmse, nse_log"):
        score(_series(1), _series(2), RULE, "pbias")


def test_a_series_without_time_index_is_refused():
    with pytest.raises(TypeError, match="indexed by time"):
        score(pd.Series([1.0, 2.0]), pd.Series([1.0, 2.0]), RULE, "nse")


def test_the_window_is_ordered_and_the_rule_refuses_unknown_keys():
    with pytest.raises(ValidationError, match="before it starts"):
        DateWindow(start=date(2020, 1, 1), end=date(2016, 1, 1))
    with pytest.raises(ValidationError, match="stations"):
        MetricRule.model_validate({"stations": ["J0014010"]})
    assert WINDOW.contains(date(2016, 6, 1)) and not WINDOW.contains(date(2015, 12, 31))


def test_the_score_columns_are_the_ones_of_the_simulation_table():
    from hydromodpy.results.storage.parquet_schemas import SIMULATION_SCHEMA

    columns = set(MetricScore.model_fields) - {"metric", "value"}
    assert columns == {"nse_window_start", "nse_window_end", "nse_n", "metric_rule_version"}
    assert columns <= set(SIMULATION_SCHEMA.names)

"""A cost and its score turn into each other by the one table of metric directions.

The search minimizes a cost; an efficiency is one minus it. That flip was
written by hand in the criteria, the single-metric route, the scalar
objective, two cases and the figures, and the figures kept their own list of
efficiencies. ``cost_of`` and ``score_of`` sit beside ``METRIC_SENSE`` and are
the one place that says it.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.criteria.series import METRICS, SeriesCriterion
from hydromodpy.results.catalog.constants import (
    METRIC_SENSE,
    UnrankedMetricError,
    cost_of,
    score_of,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "metric", sorted(name for name, sense in METRIC_SENSE.items() if sense in ("max", "min"))
)
def test_a_score_comes_back_from_its_cost(metric: str) -> None:
    assert score_of(metric, cost_of(metric, 0.25)) == pytest.approx(0.25)


def test_an_efficiency_costs_one_minus_its_score_and_an_error_costs_itself() -> None:
    assert cost_of("nse_log", 0.9) == pytest.approx(0.1)
    assert cost_of("rmse", 0.9) == pytest.approx(0.9)
    assert np.allclose(score_of("kge", np.array([0.1, 0.4])), [0.9, 0.6])


@pytest.mark.parametrize("metric", ["bias", "kge_alpha"])
def test_a_metric_best_at_a_target_has_no_cost_form(metric: str) -> None:
    with pytest.raises(UnrankedMetricError, match=metric):
        cost_of(metric, 0.1)


@pytest.mark.parametrize("metric", sorted(set(METRICS) - {"distance_gap", "distance_mean"}))
def test_every_series_criterion_costs_what_the_table_says(metric: str) -> None:
    rng = np.random.default_rng(3)
    obs = 1.0 + rng.random(730)
    sim = obs * (1.0 + 0.1 * rng.standard_normal(730))
    criterion = SeriesCriterion(metric, METRICS[metric])
    result = criterion.score(np.abs(sim), obs)
    assert result.cost == pytest.approx(cost_of(metric, result.diagnostics["score"]))


def test_the_figures_keep_no_list_of_efficiencies_of_their_own() -> None:
    from hydromodpy.display.figures import _calibration_session

    assert not hasattr(_calibration_session, "EFFICIENCIES")
    for metric in _calibration_session.METRIC_LABELS:
        assert metric in METRIC_SENSE

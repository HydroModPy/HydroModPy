"""Tests of `criteria.hydrographic_network_distance`."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.criteria import HydrographicNetworkDistance, criterion_for
from hydromodpy.calibration.criteria.base import CriterionResult
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    distance_gap,
    distance_mean,
    distance_pair,
    distance_pairs,
)
from hydromodpy.results.checks import Validity

# From test_network_criterion_reads_one_pair_per_bound.py
# The network criterion reads one ``(D_so, D_os)`` pair per bound in the cost.


def test_one_pair_keeps_its_signed_residual() -> None:
    scored = criterion_for("distance_gap").score([130.0, 100.0])
    assert scored.cost == pytest.approx(30.0)
    assert scored.signed_residual == pytest.approx(30.0)
    assert scored.diagnostics["J_signed"] == pytest.approx(30.0)


def test_two_weighted_pairs_sum_their_gaps_and_carry_no_single_residual() -> None:
    # 0.25 * (D_so, D_os) = 0.25 * (140, 100) and 0.75 * (80, 100).
    values = [35.0, 25.0, 60.0, 75.0]
    scored = criterion_for("distance_gap").score(values)
    assert scored.cost == pytest.approx(0.25 * 40.0 + 0.75 * 20.0)
    assert scored.signed_residual is None
    assert scored.diagnostics["weighted_J_signed_1"] == pytest.approx(-15.0)


def test_the_mean_estimator_sums_the_weighted_doptim() -> None:
    assert distance_mean([35.0, 25.0, 60.0, 75.0]) == pytest.approx(30.0 + 67.5)
    assert criterion_for("distance_mean").score([35.0, 25.0, 60.0, 75.0]).signed_residual is None


def test_a_negative_distance_makes_the_mean_undefined() -> None:
    assert np.isnan(distance_mean([-1.0, 5.0]))


def test_the_kernels_agree_with_the_criterion() -> None:
    values = [35.0, 25.0, 60.0, 75.0]
    assert distance_gap(values) == pytest.approx(criterion_for("distance_gap").score(values).cost)
    assert distance_pairs(values) == [(35.0, 25.0), (60.0, 75.0)]


@pytest.mark.parametrize("values", [[], [1.0], [1.0, 2.0, 3.0]])
def test_a_vector_that_is_not_made_of_pairs_is_refused(values) -> None:
    with pytest.raises(ValueError, match="pairs"):
        distance_gap(values)


def test_distance_pair_reads_one_pair_and_refuses_any_other_size() -> None:
    assert distance_pair(np.array([[35.0], [25.0]])) == (35.0, 25.0)
    with pytest.raises(ValueError, match="got 4 value"):
        distance_pair([1.0, 2.0, 3.0, 4.0])


@pytest.mark.parametrize(
    ("validity", "fatal"),
    [
        ((), False),
        ((Validity("a", True, None, "ok", fatal=True),), False),
        ((Validity("a", False, None, "coarse"),), False),
        ((Validity("a", True, None, "ok"), Validity("b", False, 1.0, "fiction", fatal=True)), True),
    ],
    ids=["no-check", "fatal-but-passed", "failed-but-not-fatal", "failed-and-fatal"],
)
def test_a_result_is_fatally_invalid_only_by_a_failed_fatal_check(validity, fatal) -> None:
    assert CriterionResult(cost=1.0, validity=validity).is_fatally_invalid is fatal


def test_an_unknown_estimator_is_refused_with_the_two_it_knows() -> None:
    with pytest.raises(ValueError, match="'distance_gap' .*'distance_mean'"):
        HydrographicNetworkDistance("distance_median")

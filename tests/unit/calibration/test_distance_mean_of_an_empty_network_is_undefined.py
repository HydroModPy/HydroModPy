"""``distance_mean`` of an empty simulated network is NaN, not a negative cost.

The pair of an empty network rebuilds ``D_so`` from the residual,
``D_os - L_cap``, so ``distance_gap`` still reads ``L_cap``. Summed as
``(D_so + D_os) / 2`` the same pair gave a negative cost, below every real
network: -1300 m for ``D_os = 1200`` and ``L_cap = 5000``.
"""

from __future__ import annotations

import math

from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    HydrographicNetworkDistance,
    distance_gap,
    distance_mean,
)
from hydromodpy.calibration.metrics.downslope_network import SeepageDistanceResult, weighted_pair

CAP = 5000.0


def _empty(d_os: float = 1200.0) -> SeepageDistanceResult:
    return SeepageDistanceResult(
        signed_gap=-CAP, status="empty_network", components={"D_os": d_os, "D_so": math.nan}
    )


def _real(d_so: float, d_os: float) -> SeepageDistanceResult:
    return SeepageDistanceResult(
        signed_gap=d_so - d_os, status="ok", components={"D_os": d_os, "D_so": d_so}
    )


def test_an_empty_network_has_no_mean_distance() -> None:
    assert math.isnan(distance_mean(weighted_pair(_empty())))


def test_one_empty_bound_of_two_makes_the_mean_undefined() -> None:
    pairs = weighted_pair(_real(2000.0, 1200.0), 0.5) + weighted_pair(_empty(), 0.5)

    assert math.isnan(distance_mean(pairs))


def test_the_gap_of_an_empty_network_is_still_the_cap() -> None:
    assert distance_gap(weighted_pair(_empty())) == CAP


def test_a_real_network_keeps_its_mean() -> None:
    assert distance_mean(weighted_pair(_real(2000.0, 1200.0))) == 1600.0


def test_a_network_lying_on_the_map_scores_zero_not_nan() -> None:
    assert distance_mean(weighted_pair(_real(0.0, 0.0))) == 0.0


def test_the_criterion_returns_nan_for_an_empty_network() -> None:
    result = HydrographicNetworkDistance("distance_mean").score(weighted_pair(_empty()))

    assert math.isnan(result.cost)

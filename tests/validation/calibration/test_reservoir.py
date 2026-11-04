"""Calibration of one and two lumped reservoirs.

Compared with: the reservoir parameters that generated the synthetic outflow record.
"""

from __future__ import annotations

import math

import pytest

from tests._helpers.tolerances import tol
from tests.validation.calibration.helpers import best_values
from tests.validation.helpers import assert_metric_below
from validation_cases.calibration.reservoir.experiment import (
    ONE_RESERVOIR_CASE,
    TWO_RESERVOIR_CASE,
    build_calibration,
)

NOT_APPLICABLE = {
    "*": "The forward model is a lumped reservoir (one or two in series) integrated by explicit Euler in NumPy. No groundwater solver is involved.",
}


@pytest.mark.validation
@pytest.mark.fast
def test_one_reservoir_nelder_mead_recovers_truth() -> None:
    engine, _ = build_calibration(
        case=ONE_RESERVOIR_CASE,
        optimizer_name="scipy_nelder_mead",
        max_trials=120,
    )
    session = engine.run()

    best = best_values(session)
    truth = ONE_RESERVOIR_CASE.truth
    drift_tol = tol("reservoir_calibration_validation__recovered_log10_k_and_n_drift_from_truth")
    assert math.isfinite(session.best.cost)
    assert_metric_below(
        "Distance of log10 k to the truth",
        abs(math.log10(best["k"]) - math.log10(truth["k"])),
        drift_tol,
    )
    assert_metric_below("Distance of n to the truth", abs(best["n"] - truth["n"]), drift_tol)


@pytest.mark.validation
@pytest.mark.slow
def test_two_reservoir_de_recovers_truth() -> None:
    engine, _ = build_calibration(
        case=TWO_RESERVOIR_CASE,
        optimizer_name="scipy_de",
        max_trials=100,
    )
    session = engine.run()

    best = best_values(session)
    truth = TWO_RESERVOIR_CASE.truth
    assert math.isfinite(session.best.cost)
    assert_metric_below(
        "Distance of log10 k1 to the truth",
        abs(math.log10(best["k1"]) - math.log10(truth["k1"])),
        0.5,
    )
    assert_metric_below(
        "Distance of log10 k2 to the truth",
        abs(math.log10(best["k2"]) - math.log10(truth["k2"])),
        0.5,
    )

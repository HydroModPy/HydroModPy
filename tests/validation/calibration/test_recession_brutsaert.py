"""Calibration of a Brutsaert-Nieber recession law.

Compared with: the parameters `a` and `b` of the recession `dQ/dt = -a Q^b` that generated the synthetic discharge.
"""

from __future__ import annotations

import math

import pytest

from tests.validation.helpers import assert_metric_below
from validation_cases.calibration.recession_brutsaert.experiment import (
    BRUTSAERT_RECESSION_CASE,
    build_calibration,
)


def _best_values(session) -> dict[str, float]:
    completed = [r for r in session.history if r.status == "completed"]
    assert completed, "calibration produced no completed trials"
    best = min(completed, key=lambda r: r.objective_value)
    values = best.metadata.get("values") if best.metadata else None
    assert values, "evaluator did not stash values in metadata"
    return dict(values)


@pytest.mark.validation
@pytest.mark.fast
def test_recession_brutsaert_nelder_mead_recovers_truth() -> None:
    engine, _ = build_calibration(
        case=BRUTSAERT_RECESSION_CASE,
        optimizer_name="scipy_nelder_mead",
        max_iter=100,
    )
    session = engine.run()

    best = _best_values(session)
    truth = BRUTSAERT_RECESSION_CASE.truth
    assert math.isfinite(session.best.objective_value)
    # a is log-transformed, b is linear
    assert_metric_below(
        "Distance of log10 a to the truth", abs(math.log10(best["a"]) - math.log10(truth["a"])), 0.2
    )
    assert_metric_below("Distance of b to the truth", abs(best["b"] - truth["b"]), 0.25)

"""Calibration of T and S on a 1D transient confined aquifer.

Compared with: the transmissivity and storativity that generated the synthetic head record.
"""

from __future__ import annotations

import math

import pytest

from tests.validation.helpers import assert_metric_below
from validation_cases.calibration.groundwater_1d.experiment import (
    GROUNDWATER_1D_CASE,
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
@pytest.mark.transient
@pytest.mark.fast
def test_groundwater_1d_nelder_mead_recovers_truth() -> None:
    engine, _ = build_calibration(
        case=GROUNDWATER_1D_CASE,
        optimizer_name="scipy_nelder_mead",
        max_iter=60,
    )
    session = engine.run()

    best = _best_values(session)
    truth = GROUNDWATER_1D_CASE.truth
    assert math.isfinite(session.best.objective_value)
    assert_metric_below(
        "Distance of log10 T to the truth", abs(math.log10(best["T"]) - math.log10(truth["T"])), 0.3
    )
    assert_metric_below(
        "Distance of log10 S to the truth", abs(math.log10(best["S"]) - math.log10(truth["S"])), 0.5
    )

"""Validate the lumped-reservoir calibration demo (one + two reservoirs)."""

from __future__ import annotations

import math

import pytest

from validation_cases.calibration.reservoir.experiment import (
    ONE_RESERVOIR_CASE,
    TWO_RESERVOIR_CASE,
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
def test_one_reservoir_nelder_mead_recovers_truth() -> None:
    engine, _ = build_calibration(
        case=ONE_RESERVOIR_CASE,
        optimizer_name="scipy_nelder_mead",
        max_iter=120,
    )
    session = engine.run()

    best = _best_values(session)
    truth = ONE_RESERVOIR_CASE.truth
    assert math.isfinite(session.best.objective_value)
    assert abs(math.log10(best["k"]) - math.log10(truth["k"])) < 0.3, best
    assert abs(best["n"] - truth["n"]) < 0.3, best


@pytest.mark.validation
@pytest.mark.slow
def test_two_reservoir_de_recovers_truth() -> None:
    engine, _ = build_calibration(
        case=TWO_RESERVOIR_CASE,
        optimizer_name="scipy_de",
        max_iter=100,
    )
    session = engine.run()

    best = _best_values(session)
    truth = TWO_RESERVOIR_CASE.truth
    assert math.isfinite(session.best.objective_value)
    assert abs(math.log10(best["k1"]) - math.log10(truth["k1"])) < 0.5, best
    assert abs(math.log10(best["k2"]) - math.log10(truth["k2"])) < 0.5, best

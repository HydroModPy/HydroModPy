"""Calibration of T and S on a 1D transient confined aquifer.

Compared with: the transmissivity and storativity that generated the synthetic head record.
"""

from __future__ import annotations

import math

import pytest

from tests.validation.calibration.helpers import best_values
from tests.validation.helpers import assert_metric_below
from validation_cases.calibration.groundwater_1d.experiment import (
    GROUNDWATER_1D_CASE,
    build_calibration,
)

NOT_APPLICABLE = {
    "*": "The forward model is a 30-line NumPy finite-difference solver inside the case module, not a HydroModPy groundwater solver. The test checks the calibration engine on it, so there is no solver to switch.",
}


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.fast
@pytest.mark.parametrize(
    ("optimizer_name", "max_trials"), [("scipy_nelder_mead", 60), ("scipy_de", 150)]
)
def test_groundwater_1d_recovers_truth(optimizer_name: str, max_trials: int) -> None:
    engine, _ = build_calibration(
        case=GROUNDWATER_1D_CASE,
        optimizer_name=optimizer_name,
        max_trials=max_trials,
    )
    session = engine.run()

    best = best_values(session)
    truth = GROUNDWATER_1D_CASE.truth
    assert math.isfinite(session.best.cost)
    assert_metric_below(
        "Distance of log10 T to the truth", abs(math.log10(best["T"]) - math.log10(truth["T"])), 0.3
    )
    assert_metric_below(
        "Distance of log10 S to the truth", abs(math.log10(best["S"]) - math.log10(truth["S"])), 0.5
    )

"""A perturbed run that fails leaves the answer without a linearized width.

``linearized`` takes one run per parameter around the answer, then the answer
itself. A run that fails, or that a water-budget rejection marks failed, used
to leave the vector of the run before it in place: the Jacobian took a stale
column, or the first failure raised a bare ``KeyError`` that lost the search
already paid for. The width is now withheld, with the reason, and the
calibrated values stand.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.runners import trial
from hydromodpy.calibration.runners.cli_runner import attach_a_linearized_width

pytestmark = pytest.mark.unit

ANSWER = {"K": 2.0, "Sy": 0.5}
CFG = SimpleNamespace(
    outputs={},
    objective_blocks=[],
    warmup_periods=0,
    scoring_window=None,
    aggregate=SimpleNamespace(min_samples=1),
    objective="nse",
    variable="discharge",
    reject_water_budget_above=1.0,
)


def _capture(*args, **kwargs):
    captured: dict = {}

    def metric_fn(trial_ctx, *, objective=None, variable=None):
        values = trial_ctx
        captured["simulated"] = np.array([values["K"], values["K"] + values["Sy"]])
        captured["observed"] = np.array([2.1, 2.4])
        return 0.0, {}

    return metric_fn, captured


def _runs(fail_when, *, scores_before_failing: bool):
    def run_trial_light(trial_ctx, values, *, metric_fn, **kwargs):
        if fail_when(values):
            if scores_before_failing:
                metric_fn(values)
            return SimpleNamespace(status="failed", error="water budget 3.2 %")
        metric_fn(values)
        return SimpleNamespace(status="completed", error=None)

    return run_trial_light


@pytest.mark.parametrize("scores_before_failing", [False, True])
def test_a_failed_perturbed_run_leaves_the_answer_without_width(
    monkeypatch, caplog, scores_before_failing
) -> None:
    monkeypatch.setattr(composite, "build_paired_vector_capture", _capture)
    monkeypatch.setattr(
        trial,
        "run_trial_light",
        _runs(
            lambda values: values["Sy"] != ANSWER["Sy"], scores_before_failing=scores_before_failing
        ),
    )
    report = SimpleNamespace(best_parameters=dict(ANSWER), parameter_uncertainty=None)

    with caplog.at_level(logging.WARNING):
        kept = attach_a_linearized_width(
            report,
            cfg=CFG,
            trial_ctx=SimpleNamespace(ctx=None),
            space=SimpleNamespace(names=("K", "Sy")),
            perturbation=0.01,
        )

    assert kept is report
    assert kept.parameter_uncertainty is None
    assert "No width is reported" in caplog.text
    assert "ended failed: water budget 3.2 %" in caplog.text


def test_the_first_run_failing_does_not_lose_the_search(monkeypatch, caplog) -> None:
    monkeypatch.setattr(composite, "build_paired_vector_capture", _capture)
    monkeypatch.setattr(
        trial, "run_trial_light", _runs(lambda values: True, scores_before_failing=False)
    )
    report = SimpleNamespace(best_parameters=dict(ANSWER), parameter_uncertainty=None)

    with caplog.at_level(logging.WARNING):
        kept = attach_a_linearized_width(
            report,
            cfg=CFG,
            trial_ctx=SimpleNamespace(ctx=None),
            space=SimpleNamespace(names=("K", "Sy")),
            perturbation=0.01,
        )

    assert kept is report
    assert "No width is reported" in caplog.text

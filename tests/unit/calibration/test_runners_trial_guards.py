"""Guards around a calibration trial: water-budget verdict, failure watch, trial sandbox.

A trial whose water balance does not close (percent discrepancy past the declared
threshold) is rejected, not scored. A search whose every trial fails stops. Each
trial solves in its own scratch folder, removed on exit unless kept.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners import trial
from hydromodpy.calibration.runners.failure_watch import (
    ConsecutiveFailureWatch,
    EveryTrialFailedError,
)
from hydromodpy.calibration.runners.pipeline_evaluator import PipelineTrialEvaluator
from hydromodpy.calibration.runners.sandbox import (
    KEEP_ENV_VAR,
    SHARED_RECHARGE_DIRNAME,
    TRIAL_RECHARGE_DIRNAME,
    TrialSandbox,
)
from hydromodpy.calibration.runners.verdict import water_budget_verdict
from hydromodpy.core.state.run_state import SlotRequest
from hydromodpy.solver.base.plan import WATER_BUDGET_METRIC

VERDICTS = [
    pytest.param(0.4, True, 0.4, id="inside the threshold"),
    pytest.param(-12.0, False, 12.0, id="negative past the threshold"),
]


@pytest.mark.parametrize(("discrepancy", "passed", "value"), VERDICTS)
def test_water_budget_verdict(discrepancy, passed, value) -> None:
    verdict = water_budget_verdict({WATER_BUDGET_METRIC: discrepancy}, threshold=5.0)

    assert verdict is not None
    assert verdict.passed is passed
    assert verdict.value == pytest.approx(value)


def test_trial_acts_on_the_verdict() -> None:
    assert "water_budget_verdict" in inspect.getsource(trial)


def test_evaluator_forwards_the_threshold() -> None:
    # The evaluator that runs the pipeline launches the trial, so it forwards the threshold.
    source = inspect.getsource(PipelineTrialEvaluator.evaluate)

    assert "reject_water_budget_above=self._cfg.reject_water_budget_above" in source


def test_rejected_trial_keeps_its_metrics() -> None:
    rejected = inspect.getsource(trial).split("water_budget_verdict(gate_metrics")[1]

    assert "metrics=dict(metrics)" in rejected
    assert 'status="failed"' in rejected
    assert "error=verdict.message" in rejected


def test_evaluator_needs_a_prepared_model() -> None:
    with pytest.raises(ValueError, match="needs_prepared_model"):
        PipelineTrialEvaluator(cfg=CalibrationConfig(), trial_ctx=None)


FAILED = (True, "no observed discharge")
INFEASIBLE = (True, "infeasible: fork: ValueError: candidate 0.8")
SCORED = (False, None)

# The last trial of each row is the one that may raise. The watch has limit=2 and
# infeasible_limit=3.
WATCH_ROWS = [
    # A point out of physical bounds says nothing about the configuration.
    pytest.param(
        [SCORED, FAILED, *[INFEASIBLE] * 5, FAILED],
        "2 calibration trials in a row",
        id="two failures in a row",
    ),
    # A search that never scores a point is refused, by the infeasible count.
    pytest.param(
        [FAILED, *[INFEASIBLE] * 3], "3 calibration trials were infeasible", id="all infeasible"
    ),
    # Once a point is scored, an infeasible region is a region to walk out of.
    pytest.param([SCORED, *[INFEASIBLE] * 10], None, id="infeasible after a score"),
]


@pytest.mark.parametrize(("trials", "refusal"), WATCH_ROWS)
def test_infeasible_trials_counted_apart(trials, refusal) -> None:
    watch = ConsecutiveFailureWatch(limit=2, infeasible_limit=3)
    *head, (failed, error) = trials
    for head_failed, head_error in head:
        watch.record(failed=head_failed, error=head_error)

    if refusal is None:
        watch.record(failed=failed, error=error)
        return
    with pytest.raises(EveryTrialFailedError, match=refusal):
        watch.record(failed=failed, error=error)


SLOT_REQUESTS = [
    pytest.param(False, False, SHARED_RECHARGE_DIRNAME, id="shared by every trial"),
    pytest.param(True, False, f"cheze_trial000004/{TRIAL_RECHARGE_DIRNAME}", id="inside the trial"),
    pytest.param(False, True, SHARED_RECHARGE_DIRNAME, id="built and not solved"),
]


@pytest.mark.parametrize(("owns_recharge", "stop_before_solve", "forcing"), SLOT_REQUESTS)
def test_sandbox_slot_request(tmp_path: Path, owns_recharge, stop_before_solve, forcing) -> None:
    sandbox = TrialSandbox("cheze", 4, scratch_root=tmp_path)

    request = sandbox.slot_request(owns_recharge=owns_recharge, stop_before_solve=stop_before_solve)

    assert request == SlotRequest(
        name="cheze_trial000004",
        stop_before_solve=stop_before_solve,
        shared_forcing_dir=tmp_path / forcing,
    )


def solved_outputs(*dirs: Path):
    return SimpleNamespace(
        solver_runs={f"run-{i}": SimpleNamespace(output_dir=d) for i, d in enumerate(dirs)}
    )


def test_keep_retains_outputs(tmp_path: Path) -> None:
    out = tmp_path / "model_trial3"
    out.mkdir()
    sandbox = TrialSandbox("m", 3, keep=True)

    with sandbox:
        sandbox.track(solved_outputs(out))

    assert out.exists()


def test_keep_env_var_retains_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(KEEP_ENV_VAR, "1")
    out = tmp_path / "model_trial4"
    out.mkdir()
    sandbox = TrialSandbox("m", 4)

    with sandbox:
        sandbox.track(solved_outputs(out))

    assert out.exists()


def test_keep_env_var_name() -> None:
    assert KEEP_ENV_VAR == "HMP_KEEP_TRIAL_SCRATCH"
    assert os.environ.get(KEEP_ENV_VAR) in (None, "", "0", "1", "true", "false")

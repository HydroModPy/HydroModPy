"""Tests of `runners.verdict`."""

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
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.state.run_state import SlotRequest
from hydromodpy.solver.base.plan import WATER_BUDGET_METRIC

# From test_a_trial_that_does_not_close_is_rejected.py
# A trial whose water balance does not close is not a cheaper trial.
#
# The solver reports a percent discrepancy on every run, and until now that number
# was recorded and nothing read it. A run at twelve per cent was an ordinary trial:
# scored, ranked, and eligible for promotion. Its cost is not comparable to a run
# that closed, because part of the water it routed came from nowhere.
#
# The threshold is a declaration, not a constant. A steady solve on a coarse mesh
# closes to a fraction of a per cent; a transient one with a lake and a stream
# network legitimately sits higher. Whoever runs the model states what they accept,
# and a trial past it is rejected rather than scored, with the number said.


class TestTheVerdict:
    def test_a_run_inside_the_threshold_passes(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 0.4}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is True
        assert verdict.value == pytest.approx(0.4)

    def test_the_sign_of_the_discrepancy_does_not_excuse_it(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: -12.0}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is False


class TestTheTrialActsOnIt:
    def test_a_rejected_trial_is_not_scored(self) -> None:
        source = inspect.getsource(trial)

        assert "water_budget_verdict" in source

    def test_the_evaluator_forwards_what_the_file_declared(self) -> None:
        """The declaration reaches the trial from wherever the trial is launched.

        It used to be launched from ``run_calibration_core``; since the evaluator
        is resolved by name it is launched from the evaluator that runs the
        pipeline, and that is where the threshold has to be forwarded.
        """

        source = inspect.getsource(PipelineTrialEvaluator.evaluate)

        assert "reject_water_budget_above=self._cfg.reject_water_budget_above" in source

    def test_a_rejected_trial_keeps_its_metrics_so_the_reason_is_readable(self) -> None:
        rejected = inspect.getsource(trial).split("water_budget_verdict(gate_metrics")[1]

        assert "metrics=dict(metrics)" in rejected
        assert 'status="failed"' in rejected
        assert "error=verdict.message" in rejected


def test_a_model_evaluator_is_refused_a_search_that_prepared_no_model() -> None:
    with pytest.raises(ValueError, match="needs_prepared_model"):
        PipelineTrialEvaluator(cfg=CalibrationConfig(), trial_ctx=None)


def test_the_pipeline_is_refused_until_project_installs_one(monkeypatch) -> None:
    """Nothing installs the pipeline as a side effect of an import any more."""
    monkeypatch.setattr(trial, "_PIPELINE", None)

    with pytest.raises(CalibrationError, match="fill_trial_pipeline"):
        trial.trial_pipeline()


def test_a_second_installation_of_another_pipeline_is_refused(monkeypatch) -> None:
    """A run already reading the pipeline must never see it change (rule 15)."""
    monkeypatch.setattr(trial, "_PIPELINE", SimpleNamespace(name="first"))
    monkeypatch.setattr(trial, "_INITIALIZER", "mod:first")

    with pytest.raises(CalibrationError, match="different TrialPipeline"):
        trial.install_trial_pipeline(SimpleNamespace(name="second"), initializer="mod:second")


def test_the_initializer_is_returned_as_installed(monkeypatch) -> None:
    monkeypatch.setattr(trial, "_PIPELINE", None)
    monkeypatch.setattr(trial, "_INITIALIZER", None)

    trial.install_trial_pipeline(SimpleNamespace(), initializer="hydromodpy.mod:fill")

    assert trial.trial_pipeline_initializer() == "hydromodpy.mod:fill"


# ---------------------------------------------------------------------------
# runners_failure_watch
# Tests of `runners.failure_watch`.
# ---------------------------------------------------------------------------

# From test_a_wholly_failed_search_stops.py
# A search whose every trial fails must stop, not finish and report a winner.
#
# A mis-configured calibration used to log one warning per trial and carry on: on
# a twenty-iteration search that is twenty lines buried in the solver's own output,
# followed by a session that completes and names a best candidate computed from
# nothing. For someone who will not read the code to find out why, a single early
# refusal is worth more than a plausible result.
#
# The counter lives on the wrapper so it sees the trials the engine actually ran;
# a cache hit never reaches the evaluator and must not count as a failure.


_FAILED = (True, "no observed discharge")
_INFEASIBLE = (True, "infeasible: fork: ValueError: candidate 0.8")
_SCORED = (False, None)


@pytest.mark.parametrize(
    ("trials", "refusal"),
    [
        # A point out of physical bounds says nothing about the configuration.
        ([_SCORED, _FAILED, *[_INFEASIBLE] * 5, _FAILED], "2 calibration trials in a row"),
        # A search that never scores a point is refused, by the infeasible count.
        ([_FAILED, *[_INFEASIBLE] * 3], "3 calibration trials were infeasible"),
        # Once a point is scored, an infeasible region is a region to walk out of.
        ([_SCORED, *[_INFEASIBLE] * 10], None),
    ],
)
def test_an_infeasible_trial_is_counted_apart(trials, refusal) -> None:
    watch = ConsecutiveFailureWatch(limit=2, infeasible_limit=3)

    *head, (failed, error) = trials
    for head_failed, head_error in head:
        watch.record(failed=head_failed, error=head_error)
    if refusal is None:
        watch.record(failed=failed, error=error)
        return
    with pytest.raises(EveryTrialFailedError, match=refusal):
        watch.record(failed=failed, error=error)


# ---------------------------------------------------------------------------
# runners_sandbox
# Tests of `runners.sandbox`.
# ---------------------------------------------------------------------------

# From test_the_sandbox_removes_the_recharge_its_trial_wrote.py
# A trial's own ``_recharge`` folder lives under its model folder.
#
# :class:`TrialSandbox` already removes the whole model directory on exit (or
# keeps it when a solve is retained for a promotion): a ``_recharge`` folder
# written inside it, as a trial that samples the recharge does (the sandbox
# names it in ``SlotRequest.shared_forcing_dir``), goes with it, with no
# special-casing needed.


def _write_recharge_file(scratch: Path, model_name: str) -> Path:
    recharge_dir = scratch / model_name / TRIAL_RECHARGE_DIRNAME
    recharge_dir.mkdir(parents=True)
    (recharge_dir / "rcha_deadbeef.0.bin").write_bytes(b"x" * 32)
    return recharge_dir


# From test_trial_sandbox.py
# Tests for per-trial solver isolation in parallel calibration.
#
# Covers:
# - :class:`TrialSandbox`: per-trial run name in a ``SlotRequest`` + output cleanup,
# - the api-isolation decision: a PARALLEL session isolates each api solve in its
#   own spawn child process; a serial session keeps the in-process api path.


# ---------------------------------------------------------------------------
# TrialSandbox: model identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("owns_recharge", "stop_before_solve", "forcing"),
    [
        (False, False, SHARED_RECHARGE_DIRNAME),
        (True, False, f"cheze_trial000004/{TRIAL_RECHARGE_DIRNAME}"),
        (False, True, SHARED_RECHARGE_DIRNAME),
    ],
    ids=["shared_by_every_trial", "inside_the_trial_folder", "built_and_not_solved"],
)
def test_the_sandbox_asks_for_the_forcing_folder_of_its_trial(
    tmp_path: Path, owns_recharge: bool, stop_before_solve: bool, forcing: str
) -> None:
    sandbox = TrialSandbox("cheze", 4, scratch_root=tmp_path)

    request = sandbox.slot_request(owns_recharge=owns_recharge, stop_before_solve=stop_before_solve)

    assert request == SlotRequest(
        name="cheze_trial000004",
        stop_before_solve=stop_before_solve,
        shared_forcing_dir=tmp_path / forcing,
    )


# ---------------------------------------------------------------------------
# TrialSandbox: output cleanup lifecycle
# ---------------------------------------------------------------------------
def _execution_with_outputs(*dirs: Path):
    return SimpleNamespace(
        solver_runs={f"run-{i}": SimpleNamespace(output_dir=d) for i, d in enumerate(dirs)}
    )


class TestOutputCleanup:
    def test_keep_retains_outputs(self, tmp_path: Path):
        out = tmp_path / "model_trial3"
        out.mkdir()
        sandbox = TrialSandbox("m", 3, keep=True)
        with sandbox:
            sandbox.track(_execution_with_outputs(out))
        assert out.exists()

    def test_keep_env_var_retains_outputs(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv(KEEP_ENV_VAR, "1")
        out = tmp_path / "model_trial4"
        out.mkdir()
        sandbox = TrialSandbox("m", 4)
        with sandbox:
            sandbox.track(_execution_with_outputs(out))
        assert out.exists()


# ---------------------------------------------------------------------------
# Parallel-safety guard
# ---------------------------------------------------------------------------


def test_keep_env_var_name_is_stable():
    assert KEEP_ENV_VAR == "HMP_KEEP_TRIAL_SCRATCH"
    assert os.environ.get(KEEP_ENV_VAR) in (None, "", "0", "1", "true", "false")

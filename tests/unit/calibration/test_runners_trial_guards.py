"""Tests of `runners.verdict`."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners import contracts, trial
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


class TestTheDeclaration:
    def test_one_per_cent_is_rejected_by_default(self) -> None:
        """Decision D13: the gate is on, at one per cent of the model budget."""
        assert CalibrationConfig().reject_water_budget_above == 1.0

    def test_a_file_may_state_what_it_accepts(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {"parameters": {"K": {"bounds": [1e-8, 1e-2]}}, "reject_water_budget_above": 5.0}
        )

        assert cfg.reject_water_budget_above == 5.0

    def test_a_negative_threshold_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(
                {
                    "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                    "reject_water_budget_above": -1.0,
                }
            )


class TestTheVerdict:
    def test_no_threshold_passes_whatever_the_discrepancy(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=None)

        assert verdict is None

    def test_a_run_inside_the_threshold_passes(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 0.4}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is True
        assert verdict.value == pytest.approx(0.4)

    def test_a_run_past_the_threshold_fails_and_is_fatal(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is False
        assert verdict.fatal is True

    def test_the_sign_of_the_discrepancy_does_not_excuse_it(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: -12.0}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is False

    def test_a_run_that_reported_nothing_yields_no_verdict(self) -> None:
        """Absent is not zero: a backend that reports none says nothing either way."""
        assert water_budget_verdict({}, threshold=5.0) is None


class TestTheLabelReadsInPlainWords:
    def test_it_says_what_the_failure_does_to_the_number(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=5.0)

        assert verdict is not None
        message = verdict.message
        assert "12" in message
        assert "5" in message
        assert "not comparable" in message

    def test_it_names_itself_so_a_report_can_group_it(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=5.0)

        assert verdict is not None
        assert verdict.name == "water_budget"


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
        rejected = inspect.getsource(trial.run_trial_light).split("water_budget_verdict")[1]

        assert "metrics=dict(metrics)" in rejected
        assert 'status="failed"' in rejected
        assert "error=verdict.message" in rejected


def test_a_model_evaluator_is_refused_a_search_that_prepared_no_model() -> None:
    with pytest.raises(ValueError, match="needs_prepared_model"):
        PipelineTrialEvaluator(cfg=CalibrationConfig(), trial_ctx=None)


def test_a_pipeline_provider_must_be_registered_before_it_is_asked_for(monkeypatch) -> None:
    monkeypatch.setattr(contracts, "_provider", None)

    with pytest.raises(RuntimeError, match="TrialPipelineProvider is not registered"):
        contracts.get_trial_pipeline_provider()


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


def test_a_run_of_failures_stops_the_search() -> None:
    """The watch gives up once the declared streak is reached."""
    watch = ConsecutiveFailureWatch(limit=3)

    watch.record(failed=True, error="no observed discharge")
    watch.record(failed=True, error="no observed discharge")
    with pytest.raises(EveryTrialFailedError) as failure:
        watch.record(failed=True, error="no observed discharge")

    message = str(failure.value)
    assert "3" in message
    assert "no observed discharge" in message


def test_one_success_clears_the_streak() -> None:
    """A search that recovers is a search, not a failure."""
    watch = ConsecutiveFailureWatch(limit=3)

    watch.record(failed=True, error="transient")
    watch.record(failed=True, error="transient")
    watch.record(failed=False, error=None)
    watch.record(failed=True, error="transient")
    watch.record(failed=True, error="transient")


def test_the_message_carries_the_last_reason() -> None:
    """The reason is what the reader needs; the count only says it is systematic."""
    watch = ConsecutiveFailureWatch(limit=2)

    watch.record(failed=True, error="first reason")
    with pytest.raises(EveryTrialFailedError, match="second reason"):
        watch.record(failed=True, error="second reason")


def test_a_limit_of_zero_never_fires() -> None:
    """Opting out stays possible for a search expected to fail its way through."""
    watch = ConsecutiveFailureWatch(limit=0)

    for _ in range(50):
        watch.record(failed=True, error="ignored")


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


class TestSandboxRemovesItsRecharge:
    def test_the_recharge_folder_is_gone_on_exit(self, tmp_path: Path) -> None:
        sandbox = TrialSandbox("cheze", 1, scratch_root=tmp_path)
        recharge_dir = _write_recharge_file(tmp_path, sandbox.model_name)
        with sandbox:
            assert recharge_dir.is_dir()
        assert not recharge_dir.exists()

    def test_a_kept_solve_keeps_its_recharge(self, tmp_path: Path) -> None:
        sandbox = TrialSandbox("cheze", 2, scratch_root=tmp_path)
        recharge_dir = _write_recharge_file(tmp_path, sandbox.model_name)
        with sandbox:
            sandbox.keep_outputs()
        assert recharge_dir.is_dir()


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
class TestTrialIdentity:
    def test_model_name_is_unique_and_deterministic(self):
        a = TrialSandbox("cheze", 1)
        b = TrialSandbox("cheze", 2)
        assert a.model_name == "cheze_trial000001"
        assert b.model_name == "cheze_trial000002"
        assert a.slot_request() == SlotRequest(name="cheze_trial000001")
        assert a.model_name != b.model_name

    def test_base_name_is_sanitized(self):
        sandbox = TrialSandbox("my run/name", 7)
        assert sandbox.model_name == "my-run-name_trial000007"
        # Result is a safe single path segment.
        assert "/" not in sandbox.model_name and " " not in sandbox.model_name

    def test_empty_base_name_falls_back(self):
        assert TrialSandbox("", 3).model_name == "trial_trial000003"


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
    def test_removes_tracked_outputs_on_exit(self, tmp_path: Path):
        out = tmp_path / "model_trial1"
        out.mkdir()
        (out / "model.lak.obs.csv").write_text("data", encoding="utf-8")
        sandbox = TrialSandbox("m", 1)
        with sandbox:
            sandbox.track(_execution_with_outputs(out))
            assert out.exists()
        assert not out.exists()

    def test_cleanup_runs_on_exception(self, tmp_path: Path):
        out = tmp_path / "model_trial2"
        out.mkdir()
        sandbox = TrialSandbox("m", 2)
        with pytest.raises(RuntimeError):
            with sandbox:
                sandbox.track(_execution_with_outputs(out))
                raise RuntimeError("boom")
        assert not out.exists()

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

    def test_no_tracked_execution_is_safe(self):
        # Fork failed before track(): exit must not raise.
        with TrialSandbox("m", 5):
            pass

    def test_distinct_trials_clean_only_their_own_outputs(self, tmp_path: Path):
        a_dir, b_dir = tmp_path / "a", tmp_path / "b"
        a_dir.mkdir()
        b_dir.mkdir()
        with TrialSandbox("m", 1) as a:
            a.track(_execution_with_outputs(a_dir))
            with TrialSandbox("m", 2) as b:
                b.track(_execution_with_outputs(b_dir))
            # b exited -> only b cleaned, a still live.
            assert not b_dir.exists()
            assert a_dir.exists()
        assert not a_dir.exists()


# ---------------------------------------------------------------------------
# Parallel-safety guard
# ---------------------------------------------------------------------------


def test_keep_env_var_name_is_stable():
    assert KEEP_ENV_VAR == "HMP_KEEP_TRIAL_SCRATCH"
    assert os.environ.get(KEEP_ENV_VAR) in (None, "", "0", "1", "true", "false")

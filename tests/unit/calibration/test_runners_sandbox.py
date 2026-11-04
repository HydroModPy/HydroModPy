"""Tests of `runners.sandbox`."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.runners.cli_runner import _api_isolation_needed
from hydromodpy.calibration.runners.sandbox import KEEP_ENV_VAR, TrialSandbox
from hydromodpy.solver.modflow6.builders.recharge import TRIAL_RECHARGE_DIRNAME

# From test_the_sandbox_removes_the_recharge_its_trial_wrote.py
# A trial's own ``_recharge`` folder lives under its model folder.
#
# :class:`TrialSandbox` already removes the whole model directory on exit (or
# keeps it when a solve is retained for a promotion): a ``_recharge`` folder
# written inside it, as a trial that samples the recharge does
# (:mod:`hydromodpy.solver.modflow6.builders.recharge`, ``§9.2``), goes with it,
# with no special-casing needed.


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
# - :class:`TrialSandbox`: per-trial ``model_name_override`` + output cleanup,
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
        assert a.flow_overrides == {"model_name_override": "cheze_trial000001"}
        assert a.model_name != b.model_name

    def test_base_name_is_sanitized(self):
        sandbox = TrialSandbox("my run/name", 7)
        assert sandbox.model_name == "my-run-name_trial000007"
        # Result is a safe single path segment.
        assert "/" not in sandbox.model_name and " " not in sandbox.model_name

    def test_empty_base_name_falls_back(self):
        assert TrialSandbox("", 3).model_name == "trial_trial000003"


# ---------------------------------------------------------------------------
# TrialSandbox: output cleanup lifecycle
# ---------------------------------------------------------------------------
def _execution_with_outputs(*dirs: Path):
    return SimpleNamespace(output_dirs_by_run_id={f"run-{i}": d for i, d in enumerate(dirs)})


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
class TestApiIsolation:
    def test_parallel_session_isolates_api(self):
        # Any parallel session isolates api solves. The decision is on
        # parallelism, not the declared mf6_runner: a marnage (exposed_band)
        # coupling forces the effective api runner even when mf6_runner stays at
        # its subprocess default, and _run_via_api is reached only by an api
        # solve, so concurrent api solves always get their own libmf6 process.
        assert _api_isolation_needed(4) is True
        assert _api_isolation_needed(2) is True

    def test_serial_session_keeps_api_in_process(self):
        # Serial keeps the in-process api path (live progress bar, no spawn).
        assert _api_isolation_needed(1) is False


def test_keep_env_var_name_is_stable():
    assert KEEP_ENV_VAR == "HMP_KEEP_TRIAL_SCRATCH"
    assert os.environ.get(KEEP_ENV_VAR) in (None, "", "0", "1", "true", "false")

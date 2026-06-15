"""Tests for per-trial solver isolation in parallel calibration.

Covers:
- :class:`TrialSandbox`: per-trial ``model_name_override`` + output cleanup,
- the parallel-safety guard that rejects the in-process ``api`` runner.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.cli_runner import _assert_parallel_safe
from hydromodpy.calibration.runners.sandbox import KEEP_ENV_VAR, TrialSandbox

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


def _trial_ctx_with_runner(runner: str | None):
    runtime = SimpleNamespace(mf6_runner=runner) if runner is not None else SimpleNamespace()
    cfg = SimpleNamespace(modflow6=SimpleNamespace(runtime=runtime))
    return SimpleNamespace(ctx=SimpleNamespace(cfg=cfg))


class TestParallelGuard:
    def test_api_runner_is_rejected_when_parallel(self):
        with pytest.raises(ValueError, match="api"):
            _assert_parallel_safe(_trial_ctx_with_runner("api"), 4)

    def test_subprocess_runner_is_allowed(self):
        _assert_parallel_safe(_trial_ctx_with_runner("subprocess"), 4)

    def test_missing_runner_defaults_to_subprocess(self):
        _assert_parallel_safe(_trial_ctx_with_runner(None), 4)

    def test_sequential_is_always_allowed(self):
        _assert_parallel_safe(_trial_ctx_with_runner("api"), 1)


def test_keep_env_var_name_is_stable():
    assert KEEP_ENV_VAR == "HMP_KEEP_TRIAL_SCRATCH"
    assert os.environ.get(KEEP_ENV_VAR) in (None, "", "0", "1", "true", "false")

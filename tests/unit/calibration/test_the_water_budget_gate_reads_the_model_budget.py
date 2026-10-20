"""The water-balance gate reads the model budget, rejects by default, and sees the run.

At HEAD the gate read a key the trial metrics never held, so a threshold of zero
passed a run at 8 per cent. The catalog figure was the worst of the lake package,
not of the model. A simulation name with a capital letter broke the MVR writer.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibPhaseDecl, CalibrationConfig
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.phase_regime import regime_overrides
from hydromodpy.calibration.runners.verdict import water_budget_verdict
from hydromodpy.core.exceptions import SolverDivergedError
from hydromodpy.simulation.planning.plan import (
    WATER_BUDGET_METRIC,
    WATER_BUDGET_WORST_METRIC,
    RunExecutionResult,
)
from hydromodpy.solver.modflow6.build import mf6_safe_name
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    model_percent_discrepancies,
)

LISTING = """\
  LAK BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1, STRESS PERIOD   1
 PERCENT DISCREPANCY =          -2.11     PERCENT DISCREPANCY =          -2.45

  VOLUME BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1, STRESS PERIOD   1
 PERCENT DISCREPANCY =           0.02     PERCENT DISCREPANCY =           0.03
"""


def test_the_model_budget_is_not_the_lake_package_budget(tmp_path: Path) -> None:
    (tmp_path / "m.lst").write_text(LISTING)

    assert model_percent_discrepancies(tmp_path) == [0.02, 0.03]


def test_a_listing_without_block_header_still_reports(tmp_path: Path) -> None:
    (tmp_path / "m.lst").write_text(" PERCENT DISCREPANCY = 0.5\n")

    assert model_percent_discrepancies(tmp_path) == [0.5]


def test_a_simulation_name_is_lowercased() -> None:
    assert mf6_safe_name("Nancon Lake_A") == "nancon_lake_a"


def test_the_gate_is_on_by_default() -> None:
    assert CalibrationConfig().reject_water_budget_above == 1.0


class _FakeProvider:
    def __init__(self, metrics: dict[str, float], crash: Exception | None = None) -> None:
        self._metrics = metrics
        self._crash = crash

    def make_state(self, *_a, **_k):
        return object()

    def make_pipeline(self, _steps):
        def run(state):
            if self._crash is not None:
                raise self._crash
            return state

        return SimpleNamespace(run=run)

    def with_solver_launcher(self, steps, recorder):
        recorder.results["run"] = RunExecutionResult(
            primary_model=None, solver_output_dir=None, metrics=self._metrics
        )
        return steps


class _FakeTrialContext:
    kept_solves = None
    override_paths: dict = {}
    ctx = SimpleNamespace(setup=None)

    def fork(self, _values, flow_runtime_overrides=None):
        return SimpleNamespace(
            ctx=SimpleNamespace(cfg=None, execution=None),
            cfg_path=None,
            raw_toml={},
            downstream_steps=(object(),),
            earliest=0,
        )


def _run(
    monkeypatch,
    discrepancy: float | None,
    threshold: float | None,
    *,
    worst: float | None = None,
    crash: Exception | None = None,
):
    metrics = {}
    if discrepancy is not None:
        metrics[WATER_BUDGET_METRIC] = discrepancy
    if worst is not None:
        metrics[WATER_BUDGET_WORST_METRIC] = worst
    provider = _FakeProvider(metrics, crash)
    monkeypatch.setattr(trial_module, "get_trial_pipeline_provider", lambda: provider)
    return trial_module.run_trial_light(
        _FakeTrialContext(),
        {"K": 1.0},
        metric_fn=lambda *_a, **_k: (0.9, {"nse": 0.9}),
        reject_water_budget_above=threshold,
    )


def test_a_trial_past_the_threshold_is_rejected(monkeypatch) -> None:
    result = _run(monkeypatch, 8.36, 1.0)

    assert result.status == "failed"
    assert "8.36" in (result.error or "")


def test_a_trial_inside_the_threshold_completes(monkeypatch) -> None:
    assert _run(monkeypatch, 0.2, 1.0).status == "completed"


def test_a_threshold_of_zero_rejects_any_imbalance(monkeypatch) -> None:
    assert _run(monkeypatch, 0.2, 0.0).status == "failed"


def test_no_threshold_disables_the_gate(monkeypatch) -> None:
    assert _run(monkeypatch, 8.36, None).status == "completed"


def test_the_gate_reads_the_worst_step_not_the_last(monkeypatch) -> None:
    """A run that loses its balance mid-way and recovers at the end is rejected."""
    result = _run(monkeypatch, 0.02, 1.0, worst=-4.5)

    assert result.status == "failed"
    assert "4.5" in (result.error or "")


def test_a_closed_run_with_a_small_worst_step_completes(monkeypatch) -> None:
    assert _run(monkeypatch, 0.02, 1.0, worst=0.4).status == "completed"


def test_a_trial_that_reports_no_budget_is_not_rejected(monkeypatch) -> None:
    """Absent is not zero, and not an imbalance either."""
    assert _run(monkeypatch, None, 1.0).status == "completed"


def test_a_trial_that_did_not_converge_is_not_scored(monkeypatch) -> None:
    """The solver refuses a run that fails to converge; the trial never reaches the score."""
    result = _run(monkeypatch, 0.0, 1.0, crash=SolverDivergedError("did not converge"))

    assert result.status == "crashed"
    assert result.primary_metric != result.primary_metric  # nan


def test_the_verdict_prefers_the_worst_step() -> None:
    verdict = water_budget_verdict(
        {WATER_BUDGET_METRIC: 0.1, WATER_BUDGET_WORST_METRIC: -3.0}, threshold=1.0
    )

    assert verdict is not None
    assert verdict.passed is False
    assert verdict.value == pytest.approx(3.0)


def test_a_steady_phase_cannot_fit_a_lake_parameter() -> None:
    phase = CalibPhaseDecl(name="p", parameters=["lake_bedleak"], regime="steady")
    document = {
        "flow": {"sinks_sources": {"lakes": {"cheze": {}}}},
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2001-01-01"}},
    }

    with pytest.raises(ValueError, match="lake"):
        regime_overrides(phase, document)


def test_a_steady_phase_may_fit_conductivity_with_a_lake() -> None:
    phase = CalibPhaseDecl(name="p", parameters=["K"], regime="steady")
    document = {
        "flow": {"sinks_sources": {"lakes": {"cheze": {}}}},
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2001-01-01"}},
    }

    assert regime_overrides(phase, document)["flow.flow_regime"] == "steady"


def test_a_short_lake_name_does_not_claim_an_unrelated_parameter() -> None:
    """The lake name is matched as a whole word, not as a fragment of any name."""
    phase = CalibPhaseDecl(name="p", parameters=["recharge_factor"], regime="steady")
    document = {
        "flow": {"sinks_sources": {"lakes": {"a": {}}}},
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2001-01-01"}},
    }

    assert regime_overrides(phase, document)["flow.flow_regime"] == "steady"


def test_a_steady_phase_cannot_fit_a_parameter_named_after_a_lake() -> None:
    phase = CalibPhaseDecl(name="p", parameters=["cheze_k"], regime="steady")
    document = {
        "flow": {"sinks_sources": {"lakes": {"cheze": {}}}},
        "simulation": {"time": {"start_datetime": "2000-01-01", "end_datetime": "2001-01-01"}},
    }

    with pytest.raises(ValueError, match="lake"):
        regime_overrides(phase, document)

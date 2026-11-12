"""A calibration session that did not complete ends the command with the calibration exit code.

A session closed "failed" (no trial completed) or "partial" (a trial failed, or the budget ended
before the stopping rule) names how it closed, with the reason written in session.json.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.cli.exit_codes import EXIT_CALIBRATION, exit_if_session_unfinished
from hydromodpy.results.session.descriptor import read_session


class Probe:
    """An evaluator that fails the trials whose number is listed in ``failing``."""

    evaluator_id = "test_unfinished_session_probe"
    needs_prepared_model = False
    calls = 0
    failing: frozenset[int] = frozenset()

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        Probe.calls += 1
        if Probe.calls in Probe.failing:
            return TrialOutcome(
                cost=math.nan, status="failed", duration_s=0.0, error="solver diverged"
            )
        return TrialOutcome(cost=float(request.values["K"]), status="completed", duration_s=0.0)


@pytest.fixture
def probe():
    Probe.calls = 0
    Probe.failing = frozenset()
    evaluation_registry.evaluators.register(Probe, replace=True)
    try:
        yield Probe
    finally:
        evaluation_registry.evaluators.unregister(Probe.evaluator_id)


PROBE_TOML = """
[calibration]
method = "grid"
max_trials = 3
evaluator = "test_unfinished_session_probe"
use_cache = false
save_runs = "none"
method_options = { points_per_dim = 3 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def calibrate(tmp_path: Path):
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML, encoding="utf-8")
    return run_calibration_cli(path, workspace=tmp_path)


def test_a_session_where_no_trial_completed_exits_non_zero(tmp_path, probe, capsys) -> None:
    probe.failing = frozenset({1, 2, 3})
    report = calibrate(tmp_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exited:
        exit_if_session_unfinished(report)

    descriptor = read_session(report.session_dir)
    assert descriptor.status == "failed"
    assert descriptor.error_message == "no trial completed; 3 trial(s) failed: trial 1, 2, 3"
    assert exited.value.code == EXIT_CALIBRATION
    assert "closed failed: no trial completed" in capsys.readouterr().err


def test_a_partial_session_exits_non_zero_from_its_summary(tmp_path, probe, capsys) -> None:
    probe.failing = frozenset({2})
    report = calibrate(tmp_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exited:
        exit_if_session_unfinished(report.to_dict())

    assert exited.value.code == EXIT_CALIBRATION
    assert "closed partial: 1 trial(s) failed: trial 2" in capsys.readouterr().err

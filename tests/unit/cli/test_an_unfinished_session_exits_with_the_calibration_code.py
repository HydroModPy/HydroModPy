"""A calibration session that did not complete ends the command with a non-zero code.

``hmp calibrate`` and ``hmp run`` exited 0 on a session closed ``failed`` (no
trial completed) or ``partial`` (a trial failed, or the budget ended before
the stopping rule). Only a failed promotion was reported. A script chaining
calibrations read the session as done. The command now names how the session
closed, with the reason written in ``session.json``, and exits with the
calibration code.
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


class _Probe:
    """Fails the trials whose number is listed in ``failing``."""

    evaluator_id = "test_unfinished_session_probe"
    needs_prepared_model = False
    calls = 0
    failing: frozenset[int] = frozenset()

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _Probe.calls += 1
        if _Probe.calls in _Probe.failing:
            return TrialOutcome(
                cost=math.nan, status="failed", duration_s=0.0, error="solver diverged"
            )
        return TrialOutcome(cost=float(request.values["K"]), status="completed", duration_s=0.0)


@pytest.fixture
def probe():
    _Probe.calls = 0
    _Probe.failing = frozenset()
    evaluation_registry.evaluators.register(_Probe, replace=True)
    try:
        yield _Probe
    finally:
        evaluation_registry.evaluators.unregister(_Probe.evaluator_id)


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


def _calibrate(tmp_path: Path):
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML, encoding="utf-8")
    return run_calibration_cli(path, workspace=tmp_path)


def test_a_session_where_no_trial_completed_exits_non_zero(tmp_path, probe, capsys) -> None:
    probe.failing = frozenset({1, 2, 3})
    report = _calibrate(tmp_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exited:
        exit_if_session_unfinished(report)

    descriptor = read_session(report.session_dir)
    assert descriptor.status == "failed"
    assert descriptor.error_message == "no trial completed; 3 trial(s) failed: trial 1, 2, 3"
    assert exited.value.code == EXIT_CALIBRATION
    assert "closed failed: no trial completed" in capsys.readouterr().err


def test_a_partial_session_exits_non_zero_from_its_summary_too(tmp_path, probe, capsys) -> None:
    probe.failing = frozenset({2})
    report = _calibrate(tmp_path)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exited:
        exit_if_session_unfinished(report.to_dict())

    assert exited.value.code == EXIT_CALIBRATION
    assert "closed partial: 1 trial(s) failed: trial 2" in capsys.readouterr().err

"""A session left ``partial`` by a failed trial names that trial.

A search can meet its stopping rule and still close ``partial`` because one
trial failed. The message written to ``session.json`` then read the name of
the stopping rule, as if the budget had run out. It now names the failed
trials, and the stopping rule only when the rule was not met.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.results.session.descriptor import read_session


class _OneFailureProbe:
    """The second trial fails, the others complete."""

    evaluator_id = "test_one_failure_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _OneFailureProbe.calls += 1
        if _OneFailureProbe.calls == 2:
            return TrialOutcome(
                cost=math.nan, status="failed", duration_s=0.0, error="solver diverged"
            )
        return TrialOutcome(cost=float(request.values["K"]), status="completed", duration_s=0.0)


@pytest.fixture
def one_failure_probe():
    _OneFailureProbe.calls = 0
    evaluation_registry.register(_OneFailureProbe, replace=True)
    try:
        yield _OneFailureProbe
    finally:
        evaluation_registry.unregister(_OneFailureProbe.evaluator_id)


PROBE_TOML = """
[calibration]
method = "grid"
max_iter = 3
evaluator = "test_one_failure_probe"
use_cache = false
save_runs = "none"
method_options = { points_per_dim = 3 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def test_the_message_names_the_failed_trial_not_the_rule(tmp_path: Path, one_failure_probe) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML, encoding="utf-8")

    report = run_calibration_cli(path, workspace=tmp_path, return_report=True)

    descriptor = read_session(report.session_dir)
    assert report.extra["search"]["converged"] is True
    assert descriptor.status == "partial"
    assert descriptor.error_message == "1 trial(s) failed: trial 2"

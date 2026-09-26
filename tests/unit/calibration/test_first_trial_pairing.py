"""What the first trial paired against an observed record, once per phase.

``ObservableScorer.score`` (``metrics/observable_scoring.py``) writes
``<name>.n_paired`` and ``<name>.date_start`` / ``<name>.date_end`` into every
trial's components. ``_first_trial_pairing`` reads them off the first entry of
a phase's history rather than recomputed trial to trial: the pairing a search
follows is set before the first candidate is scored and does not change
after it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.runners.cli_runner import _first_trial_pairing, run_calibration_cli


def _result(trial_id: int, components: dict[str, float]) -> EvaluationResult:
    return EvaluationResult(
        trial_id=trial_id, sim_id=None, objective_value=0.1, components=components
    )


def test_reads_the_first_trial_not_a_later_one() -> None:
    history = [
        _result(
            0,
            {
                "q.n_paired": 3.0,
                "q.date_start": float(date(2001, 1, 2).toordinal()),
                "q.date_end": float(date(2001, 1, 4).toordinal()),
            },
        ),
        _result(1, {"q.n_paired": 5.0}),
    ]

    pairing = _first_trial_pairing(history)

    assert pairing == {"q": {"n_paired": 3, "start": "2001-01-02", "end": "2001-01-04"}}


def test_one_entry_per_output() -> None:
    history = [
        _result(
            0,
            {
                "outlet.n_paired": 2.0,
                "outlet.date_start": float(date(2001, 1, 1).toordinal()),
                "outlet.date_end": float(date(2001, 1, 2).toordinal()),
                "piezo.n_paired": 4.0,
                "piezo.date_start": float(date(2000, 6, 1).toordinal()),
                "piezo.date_end": float(date(2000, 6, 4).toordinal()),
            },
        )
    ]

    pairing = _first_trial_pairing(history)

    assert set(pairing) == {"outlet", "piezo"}
    assert pairing["outlet"]["n_paired"] == 2
    assert pairing["piezo"]["start"] == "2000-06-01"


def test_none_without_a_paired_output() -> None:
    history = [_result(0, {"flow.raw_cost": 1.0})]

    assert _first_trial_pairing(history) is None


def test_none_for_empty_history() -> None:
    assert _first_trial_pairing([]) is None


def test_n_paired_without_dates_still_reports_the_count() -> None:
    """A component dict missing the dates (an older run) still gives the count."""
    history = [_result(0, {"q.n_paired": 7.0})]

    pairing = _first_trial_pairing(history)

    assert pairing == {"q": {"n_paired": 7}}


# ---------------------------------------------------------------------------
# End to end: a full run through run_calibration_cli reads the first trial,
# not a later one -- no solver, a custom evaluator stands in for the model.
# ---------------------------------------------------------------------------


class _FirstTrialProbe:
    """Reports a different pairing on every trial: the report must keep the first."""

    evaluator_id = "test_first_trial_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _FirstTrialProbe.calls += 1
        first = _FirstTrialProbe.calls == 1
        n = 3 if first else 30
        end = date(2001, 1, 3) if first else date(2001, 2, 1)
        return TrialOutcome(
            cost=float(request.values["K"]),
            status="completed",
            duration_s=0.0,
            components={
                "q.n_paired": float(n),
                "q.date_start": float(date(2001, 1, 1).toordinal()),
                "q.date_end": float(end.toordinal()),
            },
        )


@pytest.fixture
def first_trial_probe():
    _FirstTrialProbe.calls = 0
    evaluation_registry.register(_FirstTrialProbe, replace=True)
    try:
        yield _FirstTrialProbe
    finally:
        evaluation_registry.unregister(_FirstTrialProbe.evaluator_id)


PROBE_TOML = """
[calibration]
method = "grid"
max_iter = 3
evaluator = "test_first_trial_probe"
use_cache = false
optimizer_kwargs = { points_per_dim = 3 }

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


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_full_run_reports_the_first_trial_not_a_later_one(
    tmp_path: Path, first_trial_probe
) -> None:
    path = _write(tmp_path, PROBE_TOML)

    report = run_calibration_cli(path, workspace=tmp_path, return_report=True)

    assert first_trial_probe.calls >= 2  # more than one trial ran
    pairing = report.extra["first_trial_pairing"]
    assert pairing == {"q": {"n_paired": 3, "start": "2001-01-01", "end": "2001-01-03"}}

"""Tests of `runners.resume`: what a reopened session may trust of a phase it already solved."""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.runners import resume
from hydromodpy.calibration.runners.resume import (
    ReusableStage,
    fingerprint_matches,
    reusable_stage,
    trials_another_cost_scored,
)

CONTEXT = {"mesh": "m1"}


def _trial(number, status, hash_, k=1e-5):
    case = None if hash_ is None else SimpleNamespace(params_hash=hash_)
    return SimpleNamespace(
        trial=number,
        status=status,
        only_case=case,
        parameters={"K": k},
    )


def test_a_phase_that_left_no_scored_trial_is_not_reused(monkeypatch) -> None:
    monkeypatch.setattr(resume, "completed_phases", lambda persistence: {"flow": object()})
    persistence = SimpleNamespace(held_trial=lambda name: None)

    assert reusable_stage(persistence, "flow") is None


def test_a_trial_with_no_recorded_hash_is_not_trusted() -> None:
    stage = ReusableStage("flow", 1, 1, 0.1, {"K": 1e-5}, None)

    assert fingerprint_matches(stage, cache_context=CONTEXT) is False


def test_only_completed_trials_are_checked_against_the_cost_of_today(monkeypatch) -> None:
    monkeypatch.setattr(resume, "physical_parameters", lambda line: line.parameters)
    good = params_hash({"K": 1e-5}, context=CONTEXT)
    lines = [
        _trial(1, "completed", good),
        _trial(2, "completed", "stale"),
        _trial(3, "completed", None),
        _trial(4, "crashed", "stale"),
    ]
    persistence = SimpleNamespace(trials=lambda phase: lines)

    assert trials_another_cost_scored(persistence, "flow", cache_context=CONTEXT) == ([2], [3])

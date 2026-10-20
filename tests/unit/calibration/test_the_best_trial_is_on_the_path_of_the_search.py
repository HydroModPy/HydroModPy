"""The best trial of a session is one the search read.

A speculative engine (Nelder-Mead with ``parallel > 1``) solves candidates its
rules then leave unread. Such a trial is real and kept, but the search froze
on the best point it read. ``best_trial`` took the minimum over every
completed trial, so a lower unread one became the promoted run, a point the
search never returned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence, PersistDetail


def _session(tmp_path: Path, *, detail: PersistDetail) -> CalibrationPersistence:
    persistence = CalibrationPersistence(tmp_path / "sessions" / "toy")
    for trial_id, cost, unused in ((1, 1.0, False), (2, 0.2, True), (3, 0.5, False)):
        persistence.append_iteration(
            ParamSuggestion(trial_id=trial_id, values={"K": float(trial_id)}),
            EvaluationResult(
                trial_id=trial_id,
                sim_id=None,
                objective_value=cost,
                status="completed",
                metadata={"speculative_unused": True} if unused else {},
            ),
            detail=detail,
        )
    return persistence


@pytest.mark.parametrize("detail", ["none", "summary", "full"])
def test_an_unread_speculative_trial_is_not_the_best(tmp_path: Path, detail: PersistDetail) -> None:
    best = _session(tmp_path, detail=detail).best_trial()

    assert best is not None
    assert best.trial == 3


def test_the_unread_trial_stays_in_the_journal(tmp_path: Path) -> None:
    trials = _session(tmp_path, detail="none").trials()

    assert [line.trial for line in trials] == [1, 2, 3]
    assert trials[1].metrics == {"speculative_unused": 1.0}

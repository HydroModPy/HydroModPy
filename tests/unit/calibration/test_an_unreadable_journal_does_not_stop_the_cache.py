"""A journal this version cannot read is skipped by the trial cache, with a warning.

Every search preloads its cache from the ``trials.jsonl`` of all the sessions
of the project. A session written before a schema change is refused by the
journal reader, and the preload used to let that refusal stop the new
calibration, after its own session had opened. Its points are now solved again.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.cache import ParamsHashCache
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.state import preload_hash_cache
from hydromodpy.results.session.journal import trials_path

pytestmark = pytest.mark.unit


def _session(project_root: Path, name: str, params_hash: str) -> Path:
    session_dir = project_root / "sessions" / name
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="a" * 32,
        case_id=name,
        site=None,
        project="p",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        objective_name="rmse",
        search_space={},
        objective_window=None,
    )
    persistence.append_iteration(
        ParamSuggestion(trial_id=1, values={"K": 1.0}),
        EvaluationResult(
            trial_id=1,
            sim_id=None,
            objective_value=0.5,
            status="completed",
            metadata={"params_hash": params_hash},
        ),
    )
    return session_dir


def test_the_cache_skips_an_unreadable_journal_and_keeps_the_others(tmp_path, caplog) -> None:
    _session(tmp_path, "today", "v2:readable")
    alpha = _session(tmp_path, "alpha", "v2:alpha")
    line = json.loads(trials_path(alpha).read_text(encoding="utf-8").splitlines()[0])
    line["schema"] = "hydromodpy.trial.v0"
    trials_path(alpha).write_text(json.dumps(line) + "\n", encoding="utf-8")
    cache = ParamsHashCache()

    with caplog.at_level(logging.WARNING):
        added = preload_hash_cache(tmp_path, cache)

    assert added == 1
    assert "v2:readable" in cache
    assert "v2:alpha" not in cache
    assert "alpha" in caplog.text
    assert "solved again" in caplog.text

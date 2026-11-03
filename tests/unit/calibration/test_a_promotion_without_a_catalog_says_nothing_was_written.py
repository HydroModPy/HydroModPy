"""A promotion that cannot write a run says so instead of handing out a ``sim_id``.

With ``[simulation.results.persistence] save_catalog = false`` a run opens no
directory and writes no seal. The default ``save_runs = "best_n"`` still asked
for the best trial to become ``runs/<case>/``: the promotion returned a
``sim_id``, the journal line pointed at an empty folder and nothing told the
user. The pipeline is replaced by a recorder, as in ``test_promotion.py``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners.promotion import promote_phase_best, promote_session
from hydromodpy.results.session.journal import read_trials
from tests.unit.calibration.test_promotion import (
    K_PATH,
    _cfg,
    _Recorder,
    _session,
)

pytestmark = pytest.mark.unit


def _trial_ctx(*, save_catalog: bool) -> Any:
    persistence = SimpleNamespace(save_catalog=save_catalog)
    results = SimpleNamespace(persistence=persistence)
    base_cfg = SimpleNamespace(simulation=SimpleNamespace(results=results))
    return SimpleNamespace(kept_solves=None, base_cfg=base_cfg)


@pytest.fixture
def recorder(monkeypatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(promotion_module, "promote_prepared_trial", rec)
    return rec


def test_a_run_that_cannot_be_written_gets_no_sim_id_and_a_named_reason(
    tmp_path, recorder, caplog
) -> None:
    persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

    with caplog.at_level(logging.WARNING):
        outcome = promote_session(
            cfg=_cfg(save_best_n=2),
            trial_ctx=_trial_ctx(save_catalog=False),
            persistence=persistence,
            project_root=tmp_path,
            phase="main",
            session_status="completed",
            override_paths={"K": K_PATH},
        )

    assert (outcome.count, outcome.best_sim_id, outcome.best_rel_dir) == (0, None, None)
    (failure,) = outcome.failures
    assert "save_catalog" in failure
    assert "save_runs" in failure
    assert recorder.calls == []
    assert all(
        line.only_case.sim_id is None and line.only_case.rel_dir is None
        for line in read_trials(persistence.directory)
    )
    assert "save_catalog" in caplog.text


def test_the_best_of_a_phase_is_not_promoted_without_a_catalog(tmp_path, recorder) -> None:
    persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

    sim_id = promote_phase_best(
        trial_ctx=_trial_ctx(save_catalog=False),
        persistence=persistence,
        phase="main",
        override_paths={"K": K_PATH},
    )

    assert sim_id is None
    assert recorder.calls == []


def test_a_catalog_that_is_kept_still_promotes(tmp_path, recorder) -> None:
    persistence = _session(tmp_path, costs={1: 0.9, 2: 0.1})

    outcome = promote_session(
        cfg=_cfg(),
        trial_ctx=_trial_ctx(save_catalog=True),
        persistence=persistence,
        project_root=tmp_path,
        phase="main",
        session_status="completed",
        override_paths={"K": K_PATH},
    )

    assert outcome.count == 1
    assert outcome.best_sim_id is not None
    assert outcome.failures == []

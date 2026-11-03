"""A reopened session adds trials only under the cost that scored its journal.

``--resume`` and ``--phase`` reopen ``sessions/<case>`` and keep its trials, and
the best trial of a phase is chosen over every line of it. A document changed
in what moves a cost would let a trial scored the old way win under the new
one, so the search refuses to start. A session that another live process of
this host still writes is refused too, since both would number their trials
alike.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.calibration import persistence as persistence_module
from hydromodpy.calibration.optim.cache import context_fingerprints, params_hash
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence, PhaseContext
from hydromodpy.calibration.runners.cli_runner import refuse_a_phase_another_cost_scored
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.results.outcome import read_outcome, write_outcome
from tests._helpers.session_documents import session_opening

pytestmark = pytest.mark.unit

PHASE = PhaseContext(name="steady_k")
SCORED_BEFORE = {"schema": "test", "calibration": "2001-2002"}
SCORED_NOW = {"schema": "test", "calibration": "2001-2003"}


def _session(tmp_path: Path) -> CalibrationPersistence:
    session_dir = tmp_path / "sessions" / "calage"
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(**session_opening("calage"))
    return persistence


def _journal(persistence: CalibrationPersistence, k: float, *, context: dict | None) -> None:
    values = {"K": k}
    metadata: dict[str, Any] = {"parameters": {"K": {"value": k}}}
    if context is not None:
        metadata["params_hash"] = params_hash(values, context=context)
    persistence.append_iteration(
        ParamSuggestion(trial_id=1, values=values),
        EvaluationResult(trial_id=1, sim_id=None, cost=0.1, status="completed", metadata=metadata),
        phase=PHASE,
    )


class TestTheCostOfAReopenedPhase:
    def test_trials_scored_by_the_same_cost_let_the_search_go_on(self, tmp_path) -> None:
        persistence = _session(tmp_path)
        _journal(persistence, 1e-5, context=SCORED_BEFORE)

        refuse_a_phase_another_cost_scored(persistence, PHASE.name, SCORED_BEFORE)

    @pytest.mark.parametrize(
        ("recorded", "changed"),
        [(True, "calibration changed since"), (False, "calibration, schema changed since")],
    )
    def test_trials_another_cost_scored_stop_the_search(
        self, tmp_path, recorded: bool, changed: str
    ) -> None:
        persistence = _session(tmp_path)
        _journal(persistence, 1e-5, context=SCORED_BEFORE)
        if recorded:
            persistence.record_context(PHASE.name, context_fingerprints(SCORED_BEFORE))

        with pytest.raises(CalibrationError, match="does not score the same way") as caught:
            refuse_a_phase_another_cost_scored(persistence, PHASE.name, SCORED_NOW)

        assert changed in str(caught.value)

    def test_another_phase_is_not_read(self, tmp_path) -> None:
        persistence = _session(tmp_path)
        _journal(persistence, 1e-5, context=SCORED_BEFORE)

        refuse_a_phase_another_cost_scored(persistence, "transient_sy", SCORED_NOW)

    def test_a_trial_without_fingerprint_is_reported_not_refused(self, tmp_path, caplog) -> None:
        persistence = _session(tmp_path)
        _journal(persistence, 1e-5, context=None)

        with caplog.at_level(logging.WARNING):
            refuse_a_phase_another_cost_scored(persistence, PHASE.name, SCORED_NOW)

        assert "recorded no fingerprint" in caplog.text


class TestAWriterStillAlive:
    def _claimed_by(self, persistence: CalibrationPersistence, pid: int) -> None:
        outcome = read_outcome(persistence.directory)
        assert outcome is not None
        write_outcome(
            persistence.directory,
            outcome.model_copy(update={"pid": pid, "host": socket.gethostname()}),
        )

    def test_a_session_another_live_process_writes_is_not_resumed(self, tmp_path) -> None:
        persistence = _session(tmp_path)
        self._claimed_by(persistence, os.getppid())

        with pytest.raises(CalibrationError, match="still written by process"):
            CalibrationPersistence(persistence.directory).resume_session()

    def test_a_session_whose_writer_is_gone_is_resumed(self, tmp_path, monkeypatch) -> None:
        persistence = _session(tmp_path)
        self._claimed_by(persistence, os.getppid())
        monkeypatch.setattr(persistence_module, "process_is_alive", lambda pid: False)

        descriptor = CalibrationPersistence(persistence.directory).resume_session()

        assert descriptor.status == "running"

    def test_this_process_resumes_its_own_session(self, tmp_path) -> None:
        persistence = _session(tmp_path)

        descriptor = CalibrationPersistence(persistence.directory).resume_session()

        assert descriptor.status == "running"


class TestARefusalWritesNothing:
    def test_a_refused_resume_leaves_the_session_files_as_they_were(
        self, tmp_path, monkeypatch
    ) -> None:
        from types import SimpleNamespace

        from hydromodpy.calibration.persistence import DEFAULT_PHASE
        from hydromodpy.calibration.runners import cli_runner

        persistence = _session(tmp_path)
        main = PhaseContext(name=DEFAULT_PHASE)
        values = {"K": 1e-5}
        persistence.append_iteration(
            ParamSuggestion(trial_id=1, values=values),
            EvaluationResult(
                trial_id=1,
                sim_id=None,
                cost=0.1,
                status="completed",
                metadata={
                    "parameters": {"K": {"value": 1e-5}},
                    "params_hash": params_hash(values, context=SCORED_BEFORE),
                },
            ),
            phase=main,
        )
        persistence.finalize_session(status="completed", best=None)
        files = [persistence.directory / "session.json", persistence.directory / "outcome.json"]
        before = [path.read_bytes() for path in files]
        monkeypatch.setattr(cli_runner, "build_cache_context", lambda **_: SCORED_NOW)
        monkeypatch.setattr(cli_runner, "resolve_override_paths", lambda _cfg: {})

        with pytest.raises(CalibrationError, match="does not score the same way"):
            cli_runner.open_calibration_session(
                tmp_path,
                "calage",
                resume=True,
                raw={},
                cfg=SimpleNamespace(),
                space=None,
                trial_ctx=None,
                project=None,
            )

        assert [path.read_bytes() for path in files] == before

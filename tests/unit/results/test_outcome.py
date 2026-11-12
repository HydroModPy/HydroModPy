"""The outcome of an attempt: written whole, read back, and read into one status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hydromodpy.results.heartbeat import Heartbeat, write_heartbeat
from hydromodpy.results.outcome import (
    OUTCOME_SCHEMA,
    Outcome,
    OutcomeError,
    effective_status,
    read_outcome,
    write_outcome,
)
from hydromodpy.results.storage.contract import RUN_OUTCOME_FILENAME

NOW = datetime(2026, 10, 14, 8, 2, 11, tzinfo=UTC)


def _outcome(status: str, **overrides) -> Outcome:
    payload = {
        "case_id": "J0014010-base",
        "site": "J0014010",
        "project": "bretagne_k",
        "attempt": 2,
        "attempt_id": "7c1e" * 8,
        "sim_id": "9a4f" * 8,
        "status": status,
        "written_by": "worker",
        "started_at": NOW,
        "host": "node12",
        "pid": 4421,
        "scheduler_job_id": "8812_17",
        "step": "run_solver",
    }
    if status != "running":
        payload["ended_at"] = NOW + timedelta(minutes=17)
        payload["exit_code"] = 0 if status == "completed" else 15
    if status == "failed":
        payload["error"] = OutcomeError(
            type="SolverError", message="mf6 did not converge at stress period 51"
        )
        payload["log_tail"] = ["...", "stress period 51 failed"]
    payload.update(overrides)
    return Outcome(**payload)


def test_a_failed_write_keeps_the_previous_document(tmp_path, monkeypatch):
    write_outcome(tmp_path, _outcome("running"))
    import hydromodpy.results.storage.json_io as json_io

    def refuse(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(json_io, "rename_over_open_file", refuse)
    with pytest.raises(OSError):
        write_outcome(tmp_path, _outcome("completed"))

    assert read_outcome(tmp_path).status == "running"
    assert [p.name for p in tmp_path.iterdir()] == [RUN_OUTCOME_FILENAME]


# Precedence of D5, case by case.


# Refusals, named.


def test_a_running_attempt_cannot_have_ended():
    with pytest.raises(ValidationError, match="running attempt has no ended_at"):
        _outcome("running", ended_at=NOW)


def test_a_finished_attempt_states_when_it_ended():
    with pytest.raises(ValidationError, match="carries its ended_at"):
        _outcome("failed", ended_at=None)


def test_a_completed_attempt_carries_no_error():
    with pytest.raises(ValidationError, match="completed attempt carries no error"):
        _outcome("completed", error=OutcomeError(type="X", message="y"))


def test_another_schema_is_refused():
    with pytest.raises(ValidationError, match=OUTCOME_SCHEMA):
        Outcome.model_validate({**_outcome("running").model_dump(by_alias=True), "schema": "other"})


def test_gc_does_not_close_a_silent_run_whose_death_is_not_proven(tmp_path):
    from hydromodpy.results.retention import RetentionPolicy, plan_gc

    run_dir = tmp_path / "runs" / "far"
    run_dir.mkdir(parents=True)
    write_outcome(run_dir, _outcome("running", host="another-host"))
    write_heartbeat(
        run_dir, Heartbeat(at=NOW, pid=4421, host="another-host", attempt_id="7c1e" * 8, step="x")
    )

    plan = plan_gc(tmp_path, RetentionPolicy(), now=NOW + timedelta(days=2))

    assert effective_status(run_dir, now=NOW + timedelta(days=2)) == "stale"
    assert plan.stale_runs == ()


# The request id is written once the inputs of the attempt are resolved. An outcome
# without it reads, and the field round-trips.


def test_death_is_proven_is_no_name_of_the_outcome_module():
    import hydromodpy.results.outcome as outcome_module

    assert "death_is_proven" not in outcome_module.__all__

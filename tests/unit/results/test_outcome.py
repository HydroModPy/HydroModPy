"""The outcome of an attempt: written whole, read back, and read into one status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

import hydromodpy.results.outcome as outcome_module
import hydromodpy.results.storage.json_io as json_io
from hydromodpy.results.heartbeat import Heartbeat, write_heartbeat
from hydromodpy.results.outcome import (
    OUTCOME_SCHEMA,
    Outcome,
    OutcomeError,
    effective_status,
    read_outcome,
    write_outcome,
)
from hydromodpy.results.retention import RetentionPolicy, plan_gc
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


def test_failed_write_keeps_previous(tmp_path, monkeypatch):
    write_outcome(tmp_path, _outcome("running"))

    def refuse(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(json_io, "rename_over_open_file", refuse)
    with pytest.raises(OSError):
        write_outcome(tmp_path, _outcome("completed"))

    assert read_outcome(tmp_path).status == "running"
    assert [p.name for p in tmp_path.iterdir()] == [RUN_OUTCOME_FILENAME]


REFUSALS = [
    pytest.param(
        "running", {"ended_at": NOW}, "running attempt has no ended_at", id="running, ended"
    ),
    pytest.param("failed", {"ended_at": None}, "carries its ended_at", id="failed, no end"),
    pytest.param(
        "completed",
        {"error": OutcomeError(type="X", message="y")},
        "completed attempt carries no error",
        id="completed, with error",
    ),
]


@pytest.mark.parametrize(("status", "overrides", "match"), REFUSALS)
def test_refusals(status, overrides, match):
    with pytest.raises(ValidationError, match=match):
        _outcome(status, **overrides)


def test_another_schema_is_refused():
    with pytest.raises(ValidationError, match=OUTCOME_SCHEMA):
        Outcome.model_validate({**_outcome("running").model_dump(by_alias=True), "schema": "other"})


def test_gc_keeps_unproven_silent_run(tmp_path):
    run_dir = tmp_path / "runs" / "far"
    run_dir.mkdir(parents=True)
    write_outcome(run_dir, _outcome("running", host="another-host"))
    write_heartbeat(
        run_dir, Heartbeat(at=NOW, pid=4421, host="another-host", attempt_id="7c1e" * 8, step="x")
    )

    plan = plan_gc(tmp_path, RetentionPolicy(), now=NOW + timedelta(days=2))

    assert effective_status(run_dir, now=NOW + timedelta(days=2)) == "stale"
    assert plan.stale_runs == ()


def test_death_is_proven_is_private():
    assert "death_is_proven" not in outcome_module.__all__

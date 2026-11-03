"""The outcome of an attempt: written whole, read back, and read into one status."""

from __future__ import annotations

import json
import os
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
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME
from tests._helpers.sealed_runs import manifest_document

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


def test_an_outcome_round_trips(tmp_path):
    outcome = _outcome("failed")
    write_outcome(tmp_path, outcome)

    assert read_outcome(tmp_path) == outcome
    assert (
        (tmp_path / RUN_OUTCOME_FILENAME)
        .read_text(encoding="utf-8")
        .startswith('{\n  "schema": "hydromodpy.outcome.v1"')
    )


def test_a_directory_without_outcome_reads_as_none(tmp_path):
    assert read_outcome(tmp_path) is None


def test_the_write_leaves_no_temporary_and_replaces_the_previous_document(tmp_path):
    write_outcome(tmp_path, _outcome("running"))
    write_outcome(tmp_path, _outcome("completed"))

    assert read_outcome(tmp_path).status == "completed"
    assert [p.name for p in tmp_path.iterdir()] == [RUN_OUTCOME_FILENAME]


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


def test_the_outcome_is_flushed_to_the_disk(tmp_path, monkeypatch):
    synced: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))

    write_outcome(tmp_path, _outcome("running"))

    assert len(synced) == 2  # the file, then its directory


# Precedence of D5, case by case.


def test_a_manifest_means_completed_whatever_the_outcome_says(tmp_path):
    write_outcome(tmp_path, _outcome("failed"))
    (tmp_path / RUN_MANIFEST_FILENAME).write_text(json.dumps(manifest_document()), encoding="utf-8")

    assert effective_status(tmp_path) == "completed"


def test_a_completed_outcome_without_manifest_is_partial(tmp_path):
    write_outcome(tmp_path, _outcome("completed"))
    assert effective_status(tmp_path) == "partial"


def test_a_failed_outcome_without_manifest_is_failed(tmp_path):
    write_outcome(tmp_path, _outcome("failed"))
    assert effective_status(tmp_path) == "failed"


def test_an_aborted_outcome_without_manifest_is_aborted(tmp_path):
    write_outcome(tmp_path, _outcome("aborted", written_by="trap", signal=15))
    assert effective_status(tmp_path) == "aborted"


def test_a_running_outcome_with_a_fresh_pulse_is_running(tmp_path):
    write_outcome(tmp_path, _outcome("running"))
    write_heartbeat(
        tmp_path, Heartbeat(at=NOW, pid=4421, host="node12", attempt_id="7c1e" * 8, step="x")
    )

    assert (
        effective_status(tmp_path, now=NOW + timedelta(seconds=10), stale_after_s=60) == "running"
    )


def test_a_running_outcome_with_an_old_pulse_is_stale(tmp_path):
    write_outcome(tmp_path, _outcome("running"))
    write_heartbeat(
        tmp_path, Heartbeat(at=NOW, pid=4421, host="node12", attempt_id="7c1e" * 8, step="x")
    )

    assert effective_status(tmp_path, now=NOW + timedelta(minutes=10), stale_after_s=60) == "stale"


def test_a_running_outcome_without_pulse_ages_from_its_own_write(tmp_path):
    write_outcome(tmp_path, _outcome("running"))

    assert effective_status(tmp_path, stale_after_s=3600) == "running"
    assert (
        effective_status(tmp_path, now=datetime.now(UTC) + timedelta(hours=2), stale_after_s=3600)
        == "stale"
    )


def test_a_directory_without_outcome_is_unknown(tmp_path):
    assert effective_status(tmp_path) == "unknown"


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


def test_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="validity"):
        Outcome.model_validate({**_outcome("running").model_dump(by_alias=True), "validity": "ok"})


def test_the_step_is_an_open_vocabulary_that_names_the_steps_of_today() -> None:
    from hydromodpy.core.pipeline_steps import STEP_NAMES

    schema = Outcome.model_json_schema()["properties"]["step"]
    assert tuple(schema["x-hmp-vocabulary"]) == STEP_NAMES
    assert schema["x-hmp-vocabulary-open"] is True
    assert _outcome("running", step="a_step_of_a_later_version").step == "a_step_of_a_later_version"


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

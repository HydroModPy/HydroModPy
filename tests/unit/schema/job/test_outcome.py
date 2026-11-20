"""The outcome of a job: the document a caller acts on, which may not say two things at once.

A success carrying an error, a failure exiting 0, a cancellation under another
code or a duration that disagrees with its timestamps would make a shim decide
the opposite of what happened. Timestamps are UTC instants, durations are in s.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.schema.job.outcome import (
    UNTYPED_ERROR_CODE,
    JobOutcome,
    OutputRecord,
    dismissed,
    error_record,
    now,
)

JOB_ID = "sha256:" + "2" * 64
STARTED = "2026-09-16T08:12:05.113000+00:00"
FINISHED = "2026-09-16T08:14:41.882000+00:00"
DURATION_S = 156.769  # FINISHED - STARTED

WATERSHED = OutputRecord(
    id="watershed_vector",
    path="outputs/watershed.gpkg",
    media_type="application/geopackage+sqlite3",
    bytes=118784,
    sha256="a" * 64,
)


def outcome_with(**overrides: object) -> JobOutcome:
    fields: dict[str, object] = {
        "job_id": JOB_ID,
        "process_id": "demo-delineate",
        "process_version": "1.2.3",
        "status": "successful",
        "exit_code": 0,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "outputs": (WATERSHED,),
    }
    return JobOutcome(**(fields | overrides))  # type: ignore[arg-type]


def failure() -> dict[str, object]:
    return error_record(ConfigValidationError("the request failed validation"))


def test_duration_is_computed_from_the_timestamps() -> None:
    outcome = outcome_with()

    assert outcome.duration_s == pytest.approx(DURATION_S, abs=1e-3)
    assert outcome.to_document()["duration_s"] == pytest.approx(DURATION_S, abs=1e-3)


def test_z_suffix_names_the_same_instant() -> None:
    # An orchestrator writes RFC 3339 and both spellings are read.
    outcome = outcome_with(started_at="2026-09-16T08:12:05.113000Z")

    assert outcome.duration_s == pytest.approx(DURATION_S, abs=1e-3)


CONTRADICTIONS = [
    pytest.param({"exit_code": 14}, "succeeded and exits", id="success exits non-zero"),
    pytest.param({"errors": (failure(),)}, "succeeded and carries", id="success with an error"),
    pytest.param(
        {"status": "failed", "exit_code": 0, "outputs": (), "errors": (failure(),)},
        "failed and exits 0",
        id="failure exits zero",
    ),
    pytest.param(
        {"status": "failed", "exit_code": 14, "outputs": ()},
        "says why nowhere",
        id="failure without a reason",
    ),
    pytest.param(
        {"status": "dismissed", "exit_code": 1, "outputs": (), "errors": (failure(),)},
        "dismissed and exits",
        id="dismissal under another code",
    ),
    pytest.param(
        {"started_at": FINISHED, "finished_at": STARTED}, "before it started", id="negative time"
    ),
    # Two wall-clock readings subtract into a duration wrong by the offset.
    pytest.param(
        {"started_at": "2026-09-16T08:12:05.113000"}, "without a UTC offset", id="no offset"
    ),
    pytest.param({"started_at": "the day before yesterday"}, "not an instant", id="not an instant"),
]


@pytest.mark.parametrize(("overrides", "message"), CONTRADICTIONS)
def test_contradictions(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        outcome_with(**overrides)


def test_dismissal_from_a_local_clock_names_the_instant() -> None:
    with pytest.raises(ValueError, match="started_at"):
        dismissed(
            job_id=JOB_ID,
            process_id="demo-delineate",
            process_version="1.2.3",
            started_at="2026-09-16T08:12:05.113000",
            exc=KeyboardInterrupt(),
        )


def test_cancelled_job_has_no_output_and_exits_130() -> None:
    outcome = dismissed(
        job_id=JOB_ID,
        process_id="demo-delineate",
        process_version="1.2.3",
        started_at=now(),
        exc=KeyboardInterrupt(),
    )

    assert outcome.status == "dismissed"
    assert outcome.exit_code == 130
    assert outcome.outputs == ()
    assert outcome.errors[0]["code"] == UNTYPED_ERROR_CODE

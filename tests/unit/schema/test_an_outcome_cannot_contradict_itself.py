"""The outcome is what a caller acts on, so it may not say two things at once.

A success carrying an error, a failure exiting 0, a cancellation under another
code, a duration that disagrees with its own timestamps: each of those makes a
shim decide the opposite of what happened. The runner is the only writer of
this document, so every one of them is refused here as the bug it is.
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

STARTED = "2026-09-16T08:12:05.113000+00:00"
FINISHED = "2026-09-16T08:14:41.882000+00:00"

WATERSHED = OutputRecord(
    id="watershed_vector",
    path="outputs/watershed.gpkg",
    media_type="application/geopackage+sqlite3",
    bytes=118784,
    sha256="a" * 64,
)


def _outcome(**overrides: object) -> JobOutcome:
    fields: dict[str, object] = {
        "job_id": "sha256:" + "2" * 64,
        "process_id": "demo-delineate",
        "process_version": "1.2.3",
        "status": "successful",
        "exit_code": 0,
        "started_at": STARTED,
        "finished_at": FINISHED,
        "outputs": (WATERSHED,),
    }
    fields.update(overrides)
    return JobOutcome(**fields)  # type: ignore[arg-type]


def _failure() -> dict[str, object]:
    return error_record(ConfigValidationError("the request failed validation"))


def test_the_duration_is_computed_from_the_two_timestamps() -> None:
    """78 of 78 real manifests carry a duration that contradicts them."""
    assert _outcome().duration_s == pytest.approx(156.769, abs=1e-3)
    assert _outcome().to_document()["duration_s"] == pytest.approx(156.769, abs=1e-3)


def test_a_success_that_exits_non_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="succeeded and exits"):
        _outcome(exit_code=14)


def test_a_success_that_carries_an_error_is_refused() -> None:
    with pytest.raises(ValueError, match="succeeded and carries"):
        _outcome(errors=(_failure(),))


def test_a_failure_that_exits_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="failed and exits 0"):
        _outcome(status="failed", exit_code=0, outputs=(), errors=(_failure(),))


def test_a_failure_that_says_why_nowhere_is_refused() -> None:
    with pytest.raises(ValueError, match="says why nowhere"):
        _outcome(status="failed", exit_code=14, outputs=())


def test_a_dismissal_under_another_exit_code_is_refused() -> None:
    with pytest.raises(ValueError, match="dismissed and exits"):
        _outcome(status="dismissed", exit_code=1, outputs=(), errors=(_failure(),))


def test_an_outcome_that_finished_before_it_started_is_refused() -> None:
    with pytest.raises(ValueError, match="before it started"):
        _outcome(started_at=FINISHED, finished_at=STARTED)


def test_an_instant_without_an_offset_is_refused() -> None:
    """Two wall-clock readings subtract into a duration wrong by the offset."""
    with pytest.raises(ValueError, match="without a UTC offset"):
        _outcome(started_at="2026-09-16T08:12:05.113000")


def test_an_instant_spelled_with_a_z_is_read() -> None:
    """An orchestrator writes RFC 3339; both spellings name the same instant."""
    outcome = _outcome(started_at="2026-09-16T08:12:05.113000Z", finished_at=FINISHED)

    assert outcome.duration_s == pytest.approx(156.769, abs=1e-3)


def test_a_timestamp_that_is_not_an_instant_is_refused() -> None:
    with pytest.raises(ValueError, match="not an instant"):
        _outcome(started_at="the day before yesterday")


def test_a_cancellation_recorded_from_a_local_clock_is_refused_by_name() -> None:
    """It fails on the instant it was handed, and says which one."""
    with pytest.raises(ValueError, match="started_at"):
        dismissed(
            job_id="sha256:" + "2" * 64,
            process_id="demo-delineate",
            process_version="1.2.3",
            started_at="2026-09-16T08:12:05.113000",
            exc=KeyboardInterrupt(),
        )


def test_a_cancelled_job_claims_no_output_and_exits_130() -> None:
    outcome = dismissed(
        job_id="sha256:" + "2" * 64,
        process_id="demo-delineate",
        process_version="1.2.3",
        started_at=now(),
        exc=KeyboardInterrupt(),
    )

    assert outcome.status == "dismissed"
    assert outcome.exit_code == 130
    assert outcome.outputs == ()
    assert outcome.errors[0]["code"] == UNTYPED_ERROR_CODE

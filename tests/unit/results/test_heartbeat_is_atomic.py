"""A reader never sees a truncated heartbeat while a writer rewrites it without pause."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hydromodpy.results.heartbeat import HeartbeatThread, heartbeat_age_s, read_heartbeat

ATTEMPT_ID = "7c1e" * 8


def test_pulse_on_entry_and_step_change(tmp_path):
    with HeartbeatThread(tmp_path, attempt_id=ATTEMPT_ID, interval_s=60, step="validate") as pulse:
        first = read_heartbeat(tmp_path)
        pulse.set_step("run_solver")
        second = read_heartbeat(tmp_path)

    assert first is not None and first.step == "validate"
    assert second is not None and second.step == "run_solver"
    assert second.at >= first.at
    assert second.pid == first.pid and second.host == first.host


def test_age_against_the_given_clock(tmp_path):
    assert heartbeat_age_s(tmp_path) is None
    with HeartbeatThread(tmp_path, attempt_id=ATTEMPT_ID, interval_s=60):
        pass
    later = datetime.now(UTC) + timedelta(seconds=90)

    age = heartbeat_age_s(tmp_path, later)
    assert age is not None and 89 < age < 100

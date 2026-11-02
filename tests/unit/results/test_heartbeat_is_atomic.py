"""A reader never sees a truncated heartbeat while a writer rewrites it without pause."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

from hydromodpy.results.heartbeat import (
    HeartbeatThread,
    heartbeat_age_s,
    heartbeat_path,
    read_heartbeat,
)

ATTEMPT_ID = "7c1e" * 8


def test_a_reader_never_sees_a_truncated_pulse_under_concurrent_writes(tmp_path):
    failures: list[BaseException] = []
    seen: list[str | None] = []
    stop = threading.Event()

    def read_forever() -> None:
        while not stop.is_set():
            try:
                beat = read_heartbeat(tmp_path)
            except Exception as exc:  # noqa: BLE001 - the point of the test is to catch any
                failures.append(exc)
                return
            if beat is not None:
                assert beat.attempt_id == ATTEMPT_ID
                seen.append(beat.step)

    readers = [threading.Thread(target=read_forever) for _ in range(3)]
    for reader in readers:
        reader.start()
    with HeartbeatThread(tmp_path, attempt_id=ATTEMPT_ID, interval_s=0.001) as pulse:
        deadline = time.monotonic() + 0.5
        step = 0
        while time.monotonic() < deadline:
            pulse.set_step(f"step_{step}")
            step += 1
    stop.set()
    for reader in readers:
        reader.join()

    assert failures == []
    assert len(seen) > 100
    assert not list(heartbeat_path(tmp_path).parent.glob("*.tmp-*"))


def test_the_thread_pulses_at_entry_and_on_every_step_change(tmp_path):
    with HeartbeatThread(tmp_path, attempt_id=ATTEMPT_ID, interval_s=60, step="validate") as pulse:
        first = read_heartbeat(tmp_path)
        pulse.set_step("run_solver")
        second = read_heartbeat(tmp_path)

    assert first is not None and first.step == "validate"
    assert second is not None and second.step == "run_solver"
    assert second.at >= first.at
    assert second.pid == first.pid and second.host == first.host


def test_the_age_of_the_pulse_is_measured_against_the_clock_given(tmp_path):
    assert heartbeat_age_s(tmp_path) is None
    with HeartbeatThread(tmp_path, attempt_id=ATTEMPT_ID, interval_s=60):
        pass
    later = datetime.now(UTC) + timedelta(seconds=90)

    age = heartbeat_age_s(tmp_path, later)
    assert age is not None and 89 < age < 100


def test_a_stopped_thread_stops_writing(tmp_path):
    pulse = HeartbeatThread(tmp_path, attempt_id=ATTEMPT_ID, interval_s=0.01)
    pulse.start()
    time.sleep(0.05)
    pulse.stop()
    frozen = heartbeat_path(tmp_path).stat().st_mtime_ns
    time.sleep(0.05)

    assert heartbeat_path(tmp_path).stat().st_mtime_ns == frozen
    assert not pulse.is_alive()


def test_heartbeat_thread_leaves_the_stop_method_of_thread_alone() -> None:
    # Python before 3.13 calls ``Thread._stop()`` when a thread ends.
    assert "_stop" not in vars(HeartbeatThread)
    thread = HeartbeatThread.__new__(HeartbeatThread)
    assert callable(thread._stop)

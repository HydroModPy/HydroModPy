"""A killed calibration must close its session instead of leaving it running.

The loop closes its session in a ``finally``: the status, the best trial, the
duration. SIGINT reaches that block because Python turns it into
KeyboardInterrupt, but SIGTERM does not. It ends the process where it stands, so
the ``finally`` never runs and the session stays ``running`` in the index
forever, with no end date and no outcome. Every scheduler stop, every container
stop, every ``kill`` sends SIGTERM.

Turning it into an exception for the duration of the run is what makes the two
signals agree: whatever ends the process, the session is closed and says how.
"""

from __future__ import annotations

import json
import os
import signal
import threading
from pathlib import Path

import pytest

from hydromodpy.core.runtime.interrupts import (
    STOP_FLAG_SCHEMA,
    StopRequested,
    TerminationRequested,
    raise_if_stop_requested,
    terminate_as_interrupt,
)
from hydromodpy.core.state.layout import STOP_FLAG_FILENAME, stop_flag_for


def _current_handler():
    return signal.getsignal(signal.SIGTERM)


def test_inside_the_block_a_termination_becomes_an_exception() -> None:
    with pytest.raises(TerminationRequested):
        with terminate_as_interrupt():
            handler = _current_handler()
            assert callable(handler)
            handler(signal.SIGTERM, None)


def test_the_previous_handler_is_put_back() -> None:
    before = _current_handler()

    with terminate_as_interrupt():
        assert _current_handler() is not before

    assert _current_handler() is before


def test_the_previous_handler_is_put_back_after_a_failure() -> None:
    before = _current_handler()

    with pytest.raises(RuntimeError):
        with terminate_as_interrupt():
            raise RuntimeError("boom")

    assert _current_handler() is before


def test_nesting_restores_one_level_at_a_time() -> None:
    before = _current_handler()

    with terminate_as_interrupt():
        outer = _current_handler()
        with terminate_as_interrupt():
            assert _current_handler() is not outer
        assert _current_handler() is outer

    assert _current_handler() is before


def test_a_termination_is_an_interruption_so_a_finally_still_runs() -> None:
    """The loop already treats KeyboardInterrupt as an abort; this joins it."""
    assert issubclass(TerminationRequested, KeyboardInterrupt)


def test_outside_the_main_thread_it_does_nothing_rather_than_failing() -> None:
    """`signal.signal` is main-thread only; a worker must not crash on that."""
    outcome: list[str] = []

    def _work() -> None:
        try:
            with terminate_as_interrupt():
                outcome.append("ran")
        except Exception as exc:  # noqa: BLE001 - the point of the test
            outcome.append(f"raised {type(exc).__name__}")

    worker = threading.Thread(target=_work)
    worker.start()
    worker.join()

    assert outcome == ["ran"]


def test_the_session_scope_installs_it_for_the_whole_run() -> None:
    """The scope, not the search: restarts side by side run the search off the main thread."""
    from hydromodpy.calibration.runners.session_scope import SessionScope, closing_session

    before = _current_handler()
    with pytest.raises(TerminationRequested):
        with closing_session(SessionScope(cfg=None, project_root=Path("."))):
            os.kill(os.getpid(), signal.SIGTERM)

    assert _current_handler() is before


def test_a_terminated_session_is_closed_as_aborted() -> None:
    """The status the session scope writes for each signal, read off the scope itself."""
    import inspect

    from hydromodpy.calibration.runners import session_scope

    scope = inspect.getsource(session_scope.closing_session)
    interrupted = scope.split("except KeyboardInterrupt as exc:")[1].split("except")[0]
    abort = inspect.getsource(session_scope.abort_session)

    assert "_interruption_error(exc)" in interrupted
    assert session_scope._interruption_error(TerminationRequested()) == "SIGTERM"
    assert session_scope._interruption_error(KeyboardInterrupt()) == "SIGINT"
    stop = StopRequested("stop requested at 2026-11-10T08:00:00+00:00")
    assert session_scope._interruption_error(stop) == str(stop)
    assert 'status="aborted"' in abort


def test_a_requested_stop_is_an_interruption_too() -> None:
    """Every block that closes a run on a signal closes it on a stop, without a line more."""
    assert issubclass(StopRequested, KeyboardInterrupt)
    assert not issubclass(StopRequested, TerminationRequested)


def test_the_stop_flag_of_a_folder_sits_in_its_internal_state() -> None:
    assert stop_flag_for(Path("runs/island")) == Path("runs/island/.hmp/stop.json")
    assert STOP_FLAG_FILENAME == "stop.json"


_FLAGS = {
    "dated": json.dumps(
        {"schema": STOP_FLAG_SCHEMA, "at": "2026-11-10T08:00:00+00:00", "host": "box"}
    ),
    "undated": json.dumps({"schema": STOP_FLAG_SCHEMA}),
    "unreadable": "{not json",
    "not a mapping": "[1, 2]",
}


@pytest.mark.parametrize(
    ("flag", "raises"),
    [
        (None, None),
        ("absent", None),
        ("dated", "stop requested at 2026-11-10T08:00:00\\+00:00"),
        ("undated", "a flag without a date"),
        ("unreadable", "an unreadable flag"),
        ("not a mapping", "a flag without a date"),
    ],
    ids=["no flag", "absent", "dated", "undated", "unreadable", "not a mapping"],
)
def test_a_flag_on_disk_stops_and_says_when(
    tmp_path: Path, flag: str | None, raises: str | None
) -> None:
    path = None if flag is None else stop_flag_for(tmp_path)
    if flag in _FLAGS:
        path.parent.mkdir(parents=True)
        path.write_text(_FLAGS[flag], encoding="utf-8")

    if raises is None:
        raise_if_stop_requested(path)
        return
    with pytest.raises(StopRequested, match=raises):
        raise_if_stop_requested(path)

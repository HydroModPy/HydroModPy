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

import signal
import threading

import pytest

from hydromodpy.core.interrupts import TerminationRequested, terminate_as_interrupt


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


def test_the_calibration_loop_installs_it() -> None:
    """The loop is where a session is opened, so it is where this belongs."""
    import inspect

    from hydromodpy.calibration.runners import cli_runner

    source = inspect.getsource(cli_runner.run_calibration_core)

    assert "terminate_as_interrupt()" in source
    assert "TerminationRequested" in source


def test_a_terminated_session_is_closed_as_aborted() -> None:
    """The status the loop writes for each signal, read off the loop itself."""
    import inspect

    from hydromodpy.calibration.runners import cli_runner

    source = inspect.getsource(cli_runner.run_calibration_core)
    terminated = source.split("except TerminationRequested:")[1].split("except")[0]

    assert 'final_status = "aborted"' in terminated
    assert '"SIGTERM"' in terminated

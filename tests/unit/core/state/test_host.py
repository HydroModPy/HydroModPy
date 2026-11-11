"""The host name and the proof that a process of this host is gone."""

from __future__ import annotations

import os
import socket

import pytest

from hydromodpy.core.state import host
from hydromodpy.core.state.host import alive_here, death_is_proven, host_name

_LIVE_PID = 4242
_DEAD_PID = 4343


@pytest.fixture
def known_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only ``_LIVE_PID`` runs on this host, so the table does not hang on real pids."""
    monkeypatch.setattr(host, "process_is_alive", lambda pid: pid == _LIVE_PID)


def test_the_host_name_is_the_one_of_the_socket() -> None:
    assert host_name() == socket.gethostname()


@pytest.mark.parametrize(
    ("same_host", "pid", "dead", "alive"),
    [
        (True, _DEAD_PID, True, False),
        (True, _LIVE_PID, False, True),
        (False, _DEAD_PID, False, False),
        (False, _LIVE_PID, False, False),
        (True, None, False, False),
    ],
    ids=[
        "same-host-dead-pid",
        "same-host-live-pid",
        "other-host-dead-pid",
        "other-host-live-pid",
        "same-host-no-pid",
    ],
)
def test_death_and_life_are_judged_on_this_host_only(
    known_processes: None, same_host: bool, pid: int | None, dead: bool, alive: bool
) -> None:
    where = host_name() if same_host else host_name() + "-elsewhere"
    assert death_is_proven(where, pid) is dead
    assert alive_here(where, pid) is alive


def test_this_process_is_alive_here() -> None:
    assert alive_here(host_name(), os.getpid()) is True
    assert death_is_proven(host_name(), os.getpid()) is False


def test_a_missing_host_proves_nothing(known_processes: None) -> None:
    assert death_is_proven(None, _DEAD_PID) is False
    assert alive_here(None, _LIVE_PID) is False


@pytest.mark.parametrize("pid", [0, -1])
def test_a_pid_that_names_no_process_is_never_alive(known_processes: None, pid: int) -> None:
    """``os.kill(0, 0)`` signals the whole group, so a pid of 0 must not read as alive."""
    assert alive_here(host_name(), pid) is False

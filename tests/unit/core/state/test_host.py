"""The host name and the proof that a process of this host is gone."""

from __future__ import annotations

import socket

from hydromodpy.core.state.host import host_name

_LIVE_PID = 4242
_DEAD_PID = 4343


def test_the_host_name_is_the_one_of_the_socket() -> None:
    assert host_name() == socket.gethostname()

"""The host name of this machine."""

from __future__ import annotations

import socket

from hydromodpy.core.state.host import host_name


def test_host_name() -> None:
    assert host_name() == socket.gethostname()

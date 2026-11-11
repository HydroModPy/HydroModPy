"""The name of this host, and the proof that a process of it is gone.

A run, a lock, a lease and a calibration session record the host and pid of
the process that writes them. A reader takes the process for dead only when it
ran on this host and its pid is gone: a process of another host is never
judged. The host name comes from the deployment (``docker run --hostname``, or
the name of the Windows server), so no environment variable sets it.
"""

from __future__ import annotations

import socket

from hydromodpy.core.state.scratch import process_is_alive


def host_name() -> str:
    """The name of this host, the one read of ``socket.gethostname()``."""
    return socket.gethostname()


def death_is_proven(host: str | None, pid: int | None) -> bool:
    """Whether the process of an attempt is gone: it ran on this host and its pid is absent."""
    return host == host_name() and pid is not None and not process_is_alive(pid)


def alive_here(host: str | None, pid: int | None) -> bool:
    """Whether a process runs on this host under that pid."""
    return host == host_name() and pid is not None and pid > 0 and process_is_alive(pid)


__all__ = ["alive_here", "death_is_proven", "host_name"]

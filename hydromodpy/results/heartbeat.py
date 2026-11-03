"""The pulse of a running attempt: ``logs/heartbeat.json``.

Why
---
A status page, a watcher or a launcher asks whether an attempt is still
alive without opening any index. The attempt answers by rewriting one small
file at a fixed interval; a reader compares its ``at`` with the clock. A
pulse older than the threshold a reader chooses means ``stale``, which is a
display word, never an authorization: only a proven death lets another
attempt take the directory.

Format
------
``{"schema": "hydromodpy.heartbeat.v1", "at": "<UTC instant>", "pid": 4421,
"host": "node12", "attempt_id": "...", "step": "run_solver"}``, written by a temporary file and one rename, so a
reader never sees a truncated pulse. :class:`HeartbeatThread` writes it in
the background; ``beat`` writes it once, at entry and at every step change.
"""

from __future__ import annotations

import os
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import ConfigDict, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.results.storage.contract import HEARTBEAT_FILENAME, RUN_LOGS_DIRNAME
from hydromodpy.results.storage.json_io import read_transient_json, write_json_atomic

HEARTBEAT_SCHEMA: Final[str] = "hydromodpy.heartbeat.v1"
"""Schema id of ``logs/heartbeat.json``."""


class Heartbeat(HydroModelBase):
    """One pulse of a running attempt."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=HEARTBEAT_SCHEMA, alias="schema", description="Schema id")
    at: datetime = Field(description="Instant of the pulse, UTC")
    pid: int = Field(description="Process of the attempt")
    host: str = Field(description="Host of the attempt")
    attempt_id: str = Field(description="Attempt the pulse belongs to")
    step: str | None = Field(default=None, description="Pipeline step under way")


def heartbeat_path(run_dir: str | Path) -> Path:
    """Return ``<run>/logs/heartbeat.json``."""
    return Path(run_dir) / RUN_LOGS_DIRNAME / HEARTBEAT_FILENAME


def write_heartbeat(run_dir: str | Path, beat: Heartbeat) -> Path:
    """Write one pulse atomically and return its path."""
    return write_json_atomic(heartbeat_path(run_dir), beat.model_dump(mode="json", by_alias=True))


def read_heartbeat(run_dir: str | Path) -> Heartbeat | None:
    """Return the last pulse, or ``None`` when the attempt never pulsed."""
    try:
        payload = read_transient_json(heartbeat_path(run_dir), HEARTBEAT_SCHEMA)
    except FileNotFoundError:
        return None
    return read_stored(Heartbeat, payload)


def heartbeat_age_s(run_dir: str | Path, now: datetime | None = None) -> float | None:
    """Return the seconds since the last pulse, or ``None`` without a pulse."""
    beat = read_heartbeat(run_dir)
    if beat is None:
        return None
    instant = now if now is not None else datetime.now(UTC)
    return (instant - beat.at).total_seconds()


class HeartbeatThread(threading.Thread):
    """Write the pulse of an attempt every ``interval_s`` seconds until stopped.

    A daemon thread: it dies with the process, which is the point. Use it as
    a context manager around the attempt, and call :meth:`set_step` when the
    pipeline moves on so the pulse says where it is.
    """

    def __init__(
        self,
        run_dir: str | Path,
        *,
        attempt_id: str,
        interval_s: float = 30.0,
        step: str | None = None,
        host: str | None = None,
        pid: int | None = None,
    ) -> None:
        super().__init__(name=f"heartbeat-{attempt_id[:8]}", daemon=True)
        if interval_s <= 0:
            raise ValueError(f"interval_s must be positive, got {interval_s}")
        self._run_dir = Path(run_dir)
        self._attempt_id = attempt_id
        self._interval_s = float(interval_s)
        self._step = step
        self._host = host if host is not None else socket.gethostname()
        self._pid = pid if pid is not None else os.getpid()
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()

    @property
    def step(self) -> str | None:
        """The step the next pulse will name."""
        return self._step

    def set_step(self, step: str | None) -> None:
        """Name the step under way and pulse at once."""
        with self._lock:
            self._step = step
        self.beat()

    def beat(self) -> Path:
        """Write one pulse now."""
        with self._lock:
            beat = Heartbeat(
                at=datetime.now(UTC),
                pid=self._pid,
                host=self._host,
                attempt_id=self._attempt_id,
                step=self._step,
            )
        return write_heartbeat(self._run_dir, beat)

    def start(self) -> None:
        """Pulse once, synchronously, then keep pulsing in the background."""
        self.beat()
        super().start()

    def run(self) -> None:
        while not self._stop_requested.wait(self._interval_s):
            self.beat()

    def stop(self) -> None:
        """Stop pulsing and wait for the thread."""
        self._stop_requested.set()
        if self.is_alive():
            self.join()

    def __enter__(self) -> HeartbeatThread:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


__all__ = [
    "HEARTBEAT_SCHEMA",
    "Heartbeat",
    "HeartbeatThread",
    "heartbeat_age_s",
    "heartbeat_path",
    "read_heartbeat",
    "write_heartbeat",
]

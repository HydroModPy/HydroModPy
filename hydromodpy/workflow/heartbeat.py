"""Background heartbeat for live simulations.

While a pipeline runs, :class:`HeartbeatPulse` refreshes
``simulations.last_heartbeat`` at a fixed interval so ``hmp gc`` and
``hmp doctor --lifecycle`` can detect zombie sims when the workspace lacks
a final ``failed`` / ``completed`` status. The default 30 s cadence keeps
the column comfortably below the 10-minute staleness cutoff.
"""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.workflow.journal import WorkflowJournal

logger = get_logger(__name__)

DEFAULT_INTERVAL_S: float = 30.0


class HeartbeatPulse(AbstractContextManager):
    """Periodically refresh ``simulations.last_heartbeat`` for ``sim_id``."""

    def __init__(
        self,
        journal: WorkflowJournal,
        sim_id: str,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
    ) -> None:
        self._journal = journal
        self._sim_id = str(sim_id)
        self._interval_s = float(interval_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def sim_id(self) -> str:
        return self._sim_id

    @property
    def interval_s(self) -> float:
        return self._interval_s

    def __enter__(self) -> HeartbeatPulse:
        self._stop.clear()
        self._beat_once("heartbeat.init_failed")
        thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"hmp-heartbeat-{self._sim_id[:8]}",
        )
        thread.start()
        self._thread = thread
        return self

    def __exit__(self, *exc: object) -> bool:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._interval_s + 5.0)
        self._thread = None
        return False

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._beat_once("heartbeat.update_failed")

    def _beat_once(self, log_event: str) -> None:
        try:
            self._journal.update_heartbeat(self._sim_id)
        except Exception as exc:
            logger.warning("%s sim_id=%s err=%s", log_event, self._sim_id, exc)


__all__ = ("HeartbeatPulse", "DEFAULT_INTERVAL_S")

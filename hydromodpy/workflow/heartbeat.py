"""Background heartbeat for live simulations.

While a pipeline runs, :class:`HeartbeatPulse` emits one ``heartbeat`` row in
``workflow_events`` at a fixed cadence and refreshes a sidecar JSON file at
``<workspace>/.hmp/running/<id8>.json``. ``hmp gc`` and ``hmp doctor --lifecycle``
derive liveness from the ``v_workflow_heartbeats`` view (MAX(ts) per run);
``hmp watch`` reads the sidecar so it stays usable even while a solve holds the
DuckDB catalog locked. The default 30 s cadence keeps both comfortably below
the 10-minute staleness cutoff.
"""

from __future__ import annotations

import json
import threading
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import running_sidecar_path

if TYPE_CHECKING:
    from hydromodpy.workflow.events import WorkflowEventStream

logger = get_logger(__name__)

DEFAULT_INTERVAL_S: float = 30.0


def write_sidecar(workspace: Path, sim_id: str, *, run_id: str, step_name: str) -> None:
    """Refresh the run's heartbeat sidecar (best-effort, never raises)."""
    try:
        path = running_sidecar_path(workspace, sim_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "sim_id": str(sim_id),
                    "run_id": str(run_id),
                    "step_name": str(step_name),
                    "ts": datetime.now(UTC).isoformat(),
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("heartbeat.sidecar_write_failed sim_id=%s err=%s", str(sim_id)[:8], exc)


def remove_sidecar(workspace: Path, sim_id: str) -> None:
    """Remove the run's heartbeat sidecar (best-effort, never raises)."""
    try:
        running_sidecar_path(workspace, sim_id).unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("heartbeat.sidecar_remove_failed sim_id=%s err=%s", str(sim_id)[:8], exc)


class HeartbeatPulse(AbstractContextManager):
    """Emit periodic ``heartbeat`` events while a step is running."""

    def __init__(
        self,
        sim_id: str,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        events: WorkflowEventStream,
        run_id: str | None = None,
        step_name: str = "pipeline",
        sidecar_workspace: Path | None = None,
    ) -> None:
        self._sim_id = str(sim_id)
        self._interval_s = float(interval_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._events = events
        self._run_id = str(run_id or sim_id)
        self._step_name = step_name
        self._sidecar_workspace = sidecar_workspace

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

    def __exit__(self, *exc: object) -> Literal[False]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._interval_s + 5.0)
        self._thread = None
        if self._sidecar_workspace is not None:
            remove_sidecar(self._sidecar_workspace, self._sim_id)
        return False

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._beat_once("heartbeat.update_failed")

    def _beat_once(self, log_event: str) -> None:
        if self._sidecar_workspace is not None:
            write_sidecar(
                self._sidecar_workspace,
                self._sim_id,
                run_id=self._run_id,
                step_name=self._step_name,
            )
        try:
            self._events.heartbeat(
                run_id=self._run_id,
                step_name=self._step_name,
                sim_id=self._sim_id,
            )
        except Exception as exc:
            logger.warning("%s sim_id=%s err=%s", log_event, self._sim_id, exc)


__all__ = ("HeartbeatPulse", "DEFAULT_INTERVAL_S", "write_sidecar", "remove_sidecar")

"""Event-stream writer over ``workflow_events``.

Append-only emission of step lifecycle and heartbeat events. The table serves
as the canonical source of truth for liveness diagnostics; the view
``v_workflow_heartbeats`` derives the current heartbeat from the event stream.

All writes go through the :class:`CatalogBackend` port; the workflow
layer never calls ``connection.execute`` directly so the T3 port-driven
writes contract is preserved.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError, JournalError
from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog

logger = get_logger(__name__)


VALID_EVENT_TYPES = frozenset({"step_start", "step_end", "heartbeat", "cancel", "log"})


class WorkflowEventStream:
    """Append-only writer for the ``workflow_events`` table.

    Every method routes through the underlying :class:`CatalogBackend`
    port (``catalog._backend``) so the workflow layer never touches the
    raw DuckDB connection. Failures are logged at debug level: event
    emission must never bring a live pipeline down.
    """

    def __init__(self, catalog: SimulationCatalog) -> None:
        self._catalog = catalog
        backend = getattr(catalog, "_backend", None)
        if backend is None:
            raise JournalError("WorkflowEventStream requires a CatalogBackend on the catalog")
        self._backend = backend

    @with_lock_retry()
    def emit(
        self,
        *,
        run_id: str,
        step_name: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Append one row to ``workflow_events``.

        Errors are caught and logged at debug level so a downed catalog
        never crashes a running step.
        """
        if event_type not in VALID_EVENT_TYPES:
            raise ConfigError(f"invalid workflow event type: {event_type!r}")
        if not run_id:
            return
        body = json.dumps(dict(payload)) if payload else None
        try:
            self._backend.execute(
                "INSERT INTO workflow_events (run_id, step_name, event_type, payload) "
                "VALUES (?, ?, ?, ?)",
                [run_id, step_name, event_type, body],
            )
        except Exception as exc:
            logger.debug(
                "workflow_events.emit_failed run_id=%s step=%s type=%s err=%s",
                run_id,
                step_name,
                event_type,
                exc,
            )

    def step_start(
        self,
        *,
        run_id: str,
        step_name: str,
        step_order: int | None = None,
    ) -> None:
        """Emit a ``step_start`` event for the lifecycle of a step."""
        payload: dict[str, Any] = {}
        if step_order is not None:
            payload["step_order"] = int(step_order)
        self.emit(
            run_id=run_id,
            step_name=step_name,
            event_type="step_start",
            payload=payload or None,
        )

    def step_end(
        self,
        *,
        run_id: str,
        step_name: str,
        status: str,
        duration_s: float | None = None,
        error: str | None = None,
    ) -> None:
        """Emit a ``step_end`` event carrying status/duration/error."""
        payload: dict[str, Any] = {"status": status}
        if duration_s is not None:
            payload["duration_s"] = float(duration_s)
        if error:
            payload["error"] = error
        self.emit(
            run_id=run_id,
            step_name=step_name,
            event_type="step_end",
            payload=payload,
        )

    def heartbeat(
        self,
        *,
        run_id: str,
        step_name: str,
        sim_id: str | None = None,
    ) -> None:
        """Emit a heartbeat event for liveness tracking."""
        payload: dict[str, Any] = {}
        if sim_id:
            payload["sim_id"] = sim_id
        self.emit(
            run_id=run_id,
            step_name=step_name,
            event_type="heartbeat",
            payload=payload or None,
        )

    def cancel(self, *, run_id: str, step_name: str, reason: str | None = None) -> None:
        """Emit a cancellation event when a step is interrupted."""
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        self.emit(
            run_id=run_id,
            step_name=step_name,
            event_type="cancel",
            payload=payload or None,
        )


__all__ = ("VALID_EVENT_TYPES", "WorkflowEventStream")

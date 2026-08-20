"""Persistence for calibration sessions and iterations.

Two sinks, one shape. The session journal under ``sessions/<name>/`` is the
truth: it is written as the calibration goes, so an interrupted run keeps its
history, and :func:`hydromodpy.results.catalog.reindex.rebuild_index` reads it
back. The DuckDB rows are the index over it, so each iteration becomes **one
row** in ``calibration_iterations`` regardless of ``save_runs`` mode.

The journal is written first, then the index: a failing database write costs a
query, never a calibration history.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.session_journal import SessionJournal, SessionTrial

PersistDetail = Literal["none", "summary", "full"]


class CalibrationStore(Protocol):
    """Store surface required by calibration persistence."""

    @property
    def connection(self) -> Any: ...


class CalibrationPersistence:
    """Idempotent writer for one calibration session.

    The shared :class:`PersistenceConfig` gates every write. When
    ``persistence.save_catalog`` is False, every method becomes a no-op, so
    calibration sessions can run fully in-memory. ``project_root`` names the
    project owning ``sessions/``; without it the session is indexed but not
    journalled, which is what a read-only report handle wants.
    """

    def __init__(
        self,
        catalog: CalibrationStore,
        persistence: PersistenceConfig | None = None,
        project_root: Path | None = None,
    ):
        self._conn = catalog.connection
        self._persistence = persistence or PersistenceConfig()
        self._project_root = project_root
        self._journal: SessionJournal | None = None

    def start_session(
        self,
        *,
        session_id: str,
        project: str,
        method: str,
        objective_name: str,
        search_space: dict[str, Any],
        config: dict,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        started_at = datetime.now(UTC)
        if self._project_root is not None:
            self._journal = SessionJournal.start(
                self._project_root,
                session_id=session_id,
                project=project,
                method=method,
                objective_name=objective_name,
                search_space=search_space,
                config=config,
                started_at=started_at,
            )
        self._conn.execute(
            """
            INSERT INTO calibration_sessions
                (session_id, project, method, objective_name,
                 n_iterations, config, started_at, status_id)
            VALUES (?, ?, ?, ?, 0, ?, ?,
                    (SELECT id FROM statuses WHERE code = 'running'))
            """,
            [
                uuid.UUID(session_id) if len(session_id) == 32 else session_id,
                project,
                method,
                objective_name,
                json.dumps(config, default=str),
                started_at,
            ],
        )

    def append_iteration(
        self,
        session_id: str,
        suggestion: ParamSuggestion,
        result: EvaluationResult,
        *,
        detail: PersistDetail = "summary",
    ) -> None:
        if not self._persistence.save_catalog:
            return
        trial = _build_trial(suggestion, result, detail)
        if self._journal is not None:
            self._journal.append(trial)
        params_json = json.dumps(trial.parameters, default=str)
        metrics_json = None if trial.metrics is None else json.dumps(trial.metrics, default=str)
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid = None
        if trial.sim_id:
            try:
                sim_uuid = uuid.UUID(trial.sim_id)
            except ValueError:
                sim_uuid = None
        self._conn.execute(
            """
            INSERT INTO calibration_iterations
                (session_id, iteration, sim_id, params_hash, parameters,
                 objective_value, metrics, status, from_cache, duration_s)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id, iteration) DO UPDATE SET
                sim_id = EXCLUDED.sim_id,
                params_hash = EXCLUDED.params_hash,
                parameters = EXCLUDED.parameters,
                objective_value = EXCLUDED.objective_value,
                metrics = EXCLUDED.metrics,
                status = EXCLUDED.status,
                from_cache = EXCLUDED.from_cache,
                duration_s = EXCLUDED.duration_s
            """,
            [
                sid,
                trial.trial,
                sim_uuid,
                trial.params_hash,
                params_json,
                trial.objective_value,
                metrics_json,
                trial.status,
                trial.from_cache,
                trial.duration_s,
            ],
        )

    def finalize_session(
        self,
        session_id: str,
        *,
        best: EvaluationResult | None,
        n_iterations: int,
        duration_s: float,
        status: str = "completed",
        error: str | None = None,
        best_sim_id: str | None = None,
    ) -> None:
        """Close the session: outcome, best trial and promoted best run.

        ``best_sim_id`` is the run promotion produced for the best trial; it
        wins over the id the evaluation carried, which stays empty for the
        lightweight trial loop.
        """
        if not self._persistence.save_catalog:
            return
        ended_at = datetime.now(UTC)
        best_run = best_sim_id or (best.sim_id if best else None)
        if self._journal is not None:
            self._journal.finish(
                status=status,
                duration_s=duration_s,
                ended_at=ended_at,
                best_trial=best.trial_id if best else None,
                best_objective=best.objective_value if best else None,
                best_sim_id=best_run,
                error_message=error,
            )
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        best_sim_uuid = None
        if best_run:
            try:
                best_sim_uuid = uuid.UUID(best_run)
            except ValueError:
                best_sim_uuid = None
        self._conn.execute(
            """
            UPDATE calibration_sessions
               SET n_iterations = ?,
                   best_sim_id = ?,
                   best_objective = ?,
                   ended_at = ?,
                   duration_s = ?,
                   status_id = (SELECT id FROM statuses WHERE code = ?),
                   error_message = ?
             WHERE session_id = ?
            """,
            [
                n_iterations,
                best_sim_uuid,
                best.objective_value if best else None,
                ended_at,
                duration_s,
                status,
                error,
                sid,
            ],
        )

    def load_iterations(self, session_id: str) -> list[dict]:
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        rows = self._conn.execute(
            """
            SELECT iteration, sim_id, params_hash, parameters,
                   objective_value, metrics, status, from_cache, duration_s
              FROM calibration_iterations
             WHERE session_id = ?
             ORDER BY iteration
            """,
            [sid],
        ).fetchall()
        out: list[dict] = []
        for (
            iteration,
            sim_id,
            params_hash,
            parameters,
            objective_value,
            metrics,
            status,
            from_cache,
            duration_s,
        ) in rows:
            out.append(
                {
                    "iteration": iteration,
                    "sim_id": str(sim_id) if sim_id else None,
                    "params_hash": params_hash,
                    "parameters": json.loads(parameters) if parameters else {},
                    "objective_value": objective_value,
                    "metrics": json.loads(metrics) if metrics else None,
                    "status": status,
                    "from_cache": bool(from_cache),
                    "duration_s": duration_s,
                }
            )
        return out

    def top_n(self, session_id: str, n: int) -> list[dict]:
        """Return the N best completed iterations (lowest objective)."""
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        rows = self._conn.execute(
            """
            SELECT iteration, sim_id, params_hash, parameters,
                   objective_value, metrics, status, duration_s
              FROM calibration_iterations
             WHERE session_id = ? AND status = 'completed'
               AND objective_value IS NOT NULL
             ORDER BY objective_value ASC
             LIMIT ?
            """,
            [sid, int(n)],
        ).fetchall()
        out: list[dict] = []
        for iteration, sim_id, params_hash, parameters, obj, metrics, status, dur in rows:
            out.append(
                {
                    "iteration": iteration,
                    "sim_id": str(sim_id) if sim_id else None,
                    "params_hash": params_hash,
                    "parameters": json.loads(parameters) if parameters else {},
                    "objective_value": obj,
                    "metrics": json.loads(metrics) if metrics else None,
                    "status": status,
                    "duration_s": dur,
                }
            )
        return out


def _build_trial(
    suggestion: ParamSuggestion,
    result: EvaluationResult,
    detail: PersistDetail,
) -> SessionTrial:
    """Return the record one evaluation writes, to the journal and the index."""
    metadata = result.metadata or {}
    parameters = metadata.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {name: {"value": value} for name, value in dict(suggestion.values).items()}
    objective = result.objective_value
    finite = isinstance(objective, (int, float)) and objective == objective
    return SessionTrial(
        trial=int(suggestion.trial_id),
        parameters=parameters,
        objective_value=float(objective) if finite else None,
        status=result.status,
        duration_s=float(result.duration_s),
        from_cache=bool(result.from_cache),
        metrics=_build_metrics(result, metadata, detail),
        params_hash=metadata.get("params_hash"),
        sim_id=result.sim_id,
    )


def _build_metrics(
    result: EvaluationResult,
    metadata: dict,
    detail: PersistDetail,
) -> dict[str, Any] | None:
    """Return the metric payload of one trial at the requested detail."""
    if detail == "none":
        return None
    payload: dict[str, Any] = {}
    if result.components:
        payload.update({str(k): v for k, v in dict(result.components).items()})
    overlay = metadata.get("materialized_overlay")
    if overlay:
        payload["materialized_overlay"] = str(overlay)
    if detail == "full":
        block_costs = metadata.get("block_costs")
        if isinstance(block_costs, dict) and block_costs:
            payload["block_costs"] = {str(k): v for k, v in block_costs.items()}
    error = metadata.get("error")
    if error:
        payload["error"] = str(error)
    return payload or None


__all__ = ["CalibrationPersistence", "PersistDetail"]

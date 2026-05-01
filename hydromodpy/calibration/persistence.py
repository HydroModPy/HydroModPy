"""DuckDB persistence for calibration sessions and iterations.

Writes through the injected calibration store connection. Each iteration
becomes **one row** in ``calibration_iterations`` regardless of ``save_runs``
mode.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from hydromodpy.calibration.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.core.config_kit.persistence import PersistenceConfig

PersistDetail = Literal["none", "summary", "full"]


class CalibrationStore(Protocol):
    """Store surface required by calibration persistence."""

    @property
    def connection(self) -> Any: ...


class CalibrationPersistence:
    """Idempotent writer for calibration rows.

    The shared :class:`PersistenceConfig` gates every DuckDB write. When
    ``persistence.save_catalog`` is False, every method becomes a no-op,
    so calibration sessions can run fully in-memory.
    """

    def __init__(
        self,
        catalog: CalibrationStore,
        persistence: PersistenceConfig | None = None,
    ):
        self._conn = catalog.connection
        self._persistence = persistence or PersistenceConfig()

    def start_session(
        self,
        *,
        session_id: str,
        project: str,
        method: str,
        objective_name: str,
        config: dict,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        self._conn.execute(
            """
            INSERT INTO calibration_sessions
                (session_id, project, method, objective_name,
                 n_iterations, config, started_at, status)
            VALUES (?, ?, ?, ?, 0, ?, ?, 'running')
            """,
            [
                uuid.UUID(session_id) if len(session_id) == 32 else session_id,
                project,
                method,
                objective_name,
                json.dumps(config, default=str),
                datetime.now(UTC),
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
        metadata = result.metadata or {}
        parameter_payload = metadata.get("parameters")
        if not isinstance(parameter_payload, dict):
            parameter_payload = {
                name: {"value": value} for name, value in dict(suggestion.values).items()
            }
        params_json = json.dumps(parameter_payload, default=str)
        params_hash = metadata.get("params_hash")
        metrics_json = _build_metrics_json(result, metadata, detail)
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        sim_uuid = None
        if result.sim_id:
            try:
                sim_uuid = uuid.UUID(result.sim_id)
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
                suggestion.trial_id,
                sim_uuid,
                params_hash,
                params_json,
                (
                    result.objective_value
                    if isinstance(result.objective_value, (int, float))
                    and result.objective_value == result.objective_value
                    else None
                ),
                metrics_json,
                result.status,
                bool(result.from_cache),
                float(result.duration_s),
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
    ) -> None:
        if not self._persistence.save_catalog:
            return
        sid = uuid.UUID(session_id) if len(session_id) == 32 else session_id
        best_sim_uuid = None
        if best and best.sim_id:
            try:
                best_sim_uuid = uuid.UUID(best.sim_id)
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
                   status = ?,
                   error_message = ?
             WHERE session_id = ?
            """,
            [
                n_iterations,
                best_sim_uuid,
                best.objective_value if best else None,
                datetime.now(UTC),
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


def _build_metrics_json(
    result: EvaluationResult,
    metadata: dict,
    detail: PersistDetail,
) -> str | None:
    if detail == "none":
        return None
    payload: dict[str, object] = {}
    if result.components:
        payload.update({str(k): v for k, v in dict(result.components).items()})
    overlay = metadata.get("materialized_overlay")
    if overlay:
        payload["materialized_overlay"] = str(overlay)
    if detail == "full":
        block_costs = metadata.get("block_costs")
        if isinstance(block_costs, dict) and block_costs:
            payload["block_costs"] = {str(k): v for k, v in block_costs.items()}
    if not payload:
        return None
    return json.dumps(payload, default=str)


__all__ = ["CalibrationPersistence", "PersistDetail"]

"""Calibration session export to legacy JSONL + manifest layout.

Owns the inverse-of-``CalibrationPersistence`` flow: read iteration rows
through the persistence helper, translate them to the legacy keys that
``hydromodpy.calibration.objective_mapping`` consumes, and write the
manifest / JSONL / model_distribution files.

This module lives in ``calibration`` so that ``results.catalog`` stays a
passive store and never imports calibration.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from hydromodpy.calibration.persistence import CalibrationPersistence

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog


def export_session(
    catalog: SimulationCatalog,
    session_id: str | UUID,
    out_dir: Path | str,
) -> Path:
    """Export one calibration session to the legacy JSONL + manifest shape.

    Writes ``iteration_history.jsonl`` (one JSON per row) plus
    ``session_manifest.json`` under ``out_dir``. Returns ``out_dir``.

    The JSONL uses the legacy keys consumed by
    ``hydromodpy.calibration.objective_mapping`` so that benchmark
    plotting tools keep working unchanged. Mapping from the catalog
    schema:

    - ``iteration_id`` <- ``iteration`` (stringified)
    - ``params_named`` <- ``parameters``
    - ``params_vector`` <- ordered values of ``parameters``
    - ``objective_total`` <- ``objective_value``
    - ``block_costs`` <- ``metrics["block_costs"]`` if present in
      ``persist_iteration_detail="full"`` mode, otherwise the flat
      ``metrics`` dict (component-only summary)
    - ``failure_reason`` <- ``status`` when not ``completed``

    When the session config has ``persist_model_distribution=True``,
    a ``model_distribution.json`` file is also produced, summarising
    each parameter across completed iterations.
    """
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    sid_str = str(session_id)
    sid = UUID(sid_str) if len(sid_str.replace("-", "")) == 32 else sid_str

    session_row = catalog._connection.execute(
        """
        SELECT session_id, project, method, objective_name,
               n_iterations, config, started_at, ended_at, status,
               best_sim_id, best_objective, duration_s
          FROM calibration_sessions
         WHERE session_id = ?
        """,
        [sid],
    ).fetchone()
    if session_row is None:
        raise ValueError(f"Unknown calibration session {session_id!r}")

    manifest_keys = (
        "session_id",
        "project",
        "method",
        "objective_name",
        "n_iterations",
        "config",
        "started_at",
        "ended_at",
        "status",
        "best_sim_id",
        "best_objective",
        "duration_s",
    )
    manifest: dict[str, Any] = {}
    config_payload: dict[str, Any] | None = None
    for key, value in zip(manifest_keys, session_row, strict=True):
        if key in {"session_id", "best_sim_id"}:
            manifest[key] = None if value is None else str(value)
        elif key == "config":
            if isinstance(value, str) and value:
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    manifest[key] = value
                else:
                    manifest[key] = decoded
                    if isinstance(decoded, dict):
                        config_payload = decoded
            else:
                manifest[key] = value
                if isinstance(value, dict):
                    config_payload = value
        else:
            manifest[key] = value
    manifest_path = out / "session_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, default=str, indent=2) + "\n",
        encoding="utf-8",
    )

    rows = CalibrationPersistence(catalog).load_iterations(str(session_id))
    jsonl_path = out / "iteration_history.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(_legacy_jsonl_row(row), default=str) + "\n")

    if config_payload and bool(config_payload.get("persist_model_distribution")):
        distribution = _build_model_distribution(rows)
        (out / "model_distribution.json").write_text(
            json.dumps(distribution, default=str, indent=2) + "\n",
            encoding="utf-8",
        )

    return out


def _legacy_jsonl_row(row: dict[str, Any]) -> dict[str, Any]:
    """Translate a calibration iteration row into the legacy JSONL shape.

    See ``hydromodpy.calibration.objective_mapping._parse_legacy_row`` for
    the consumer contract.
    """
    params = row.get("parameters") or {}
    metrics = row.get("metrics") or {}
    block_costs: dict[str, Any] = {}
    if isinstance(metrics, dict):
        nested = metrics.get("block_costs")
        if isinstance(nested, dict):
            block_costs = {str(k): v for k, v in nested.items()}
        else:
            block_costs = {str(k): v for k, v in metrics.items() if k != "block_costs"}
    status = row.get("status") or "unknown"
    failure_reason = None if status == "completed" else status
    return {
        "iteration_id": str(row.get("iteration", "")),
        "iteration": row.get("iteration"),
        "sim_id": row.get("sim_id"),
        "params_hash": row.get("params_hash"),
        "params_named": dict(params) if isinstance(params, dict) else {},
        "params_vector": ([float(v) for v in params.values()] if isinstance(params, dict) else []),
        "parameters": dict(params) if isinstance(params, dict) else {},
        "objective_total": row.get("objective_value"),
        "objective_value": row.get("objective_value"),
        "block_costs": block_costs,
        "metrics": metrics if metrics else None,
        "status": status,
        "failure_reason": failure_reason,
        "from_cache": bool(row.get("from_cache", False)),
        "duration_s": row.get("duration_s"),
    }


def _build_model_distribution(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Summarise per-parameter statistics across completed iterations."""
    by_param: dict[str, list[tuple[float, float | None]]] = {}
    for row in rows:
        if row.get("status") != "completed":
            continue
        params = row.get("parameters") or {}
        if not isinstance(params, dict):
            continue
        obj = row.get("objective_value")
        try:
            obj_value = float(obj) if obj is not None else None
        except (TypeError, ValueError):
            obj_value = None
        for name, value in params.items():
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            by_param.setdefault(str(name), []).append((v, obj_value))

    out: dict[str, dict[str, float]] = {}
    for name, samples in by_param.items():
        values = [v for v, _ in samples]
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        if n > 1:
            var = sum((v - mean) ** 2 for v in values) / (n - 1)
            std = math.sqrt(var)
        else:
            std = 0.0
        finite_obj = [(v, obj) for v, obj in samples if obj is not None and math.isfinite(obj)]
        if finite_obj:
            best = min(finite_obj, key=lambda pair: pair[1])[0]
        else:
            best = values[0]
        out[name] = {
            "min": min(values),
            "max": max(values),
            "mean": mean,
            "std": std,
            "best": best,
            "n": float(n),
        }
    return out


__all__ = ["export_session"]

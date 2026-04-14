"""Reporting helpers for model-calibration launcher sessions.

This module stays launcher-local on purpose. It summarizes what the calibration
session actually evaluated without leaking reporting concerns into the
calibration core.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.calibration.engine.config import ModelCalibrationConfig
from hydromodpy.analysis.calibration.engine.session import PreparedCalibrationSession


def _safe_float(value: Any) -> float | None:
    """Convert one optional numeric-like value to float when possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted


def _load_iteration_history(history_path: Path) -> list[dict[str, Any]]:
    """Load persisted iteration rows when the JSONL file exists."""
    if not history_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def _summarize_numeric(values: list[float]) -> dict[str, Any]:
    """Return simple descriptive statistics for one numeric vector."""
    if not values:
        return {
            "count": 0,
            "finite_count": 0,
            "min": None,
            "mean": None,
            "max": None,
            "std": None,
        }
    arr = np.asarray(values, dtype=float).ravel()
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {
            "count": int(arr.size),
            "finite_count": 0,
            "min": None,
            "mean": None,
            "max": None,
            "std": None,
        }
    return {
        "count": int(arr.size),
        "finite_count": int(finite.size),
        "min": float(np.min(finite)),
        "mean": float(np.mean(finite)),
        "max": float(np.max(finite)),
        "std": float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0,
    }


def _best_history_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the finite row with the lowest objective total."""
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        objective_total = _safe_float(row.get("objective_total"))
        if objective_total is None or not math.isfinite(objective_total):
            continue
        ranked.append((objective_total, row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _summarize_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count iteration statuses from persisted history rows."""
    counter = Counter(str(row.get("status", "unknown")) for row in rows)
    return {status: int(count) for status, count in sorted(counter.items())}


def _summarize_parameter_history(
    *,
    cfg: ModelCalibrationConfig,
    rows: list[dict[str, Any]],
    best_params: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Summarize explored parameter values across recorded iterations."""
    values_by_parameter: dict[str, list[float]] = {
        name: [] for name in cfg.parameter_names
    }
    for row in rows:
        params_named = row.get("params_named")
        if not isinstance(params_named, dict):
            continue
        for name in cfg.parameter_names:
            value = _safe_float(params_named.get(name))
            if value is not None:
                values_by_parameter[name].append(value)

    best_params = best_params if isinstance(best_params, dict) else {}
    return {
        name: {
            **_summarize_numeric(values_by_parameter[name]),
            "best_value": _safe_float(best_params.get(name)),
        }
        for name in cfg.parameter_names
    }


def _summarize_block_contributions(
    *,
    cfg: ModelCalibrationConfig,
    rows: list[dict[str, Any]],
    best_row: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Summarize per-block normalized contributions from iteration history."""
    values_by_block: dict[str, list[float]] = defaultdict(list)
    last_value_by_block: dict[str, float | None] = {}
    for row in rows:
        block_costs = row.get("block_costs")
        if not isinstance(block_costs, dict):
            continue
        for block_name, value in block_costs.items():
            numeric = _safe_float(value)
            if numeric is None:
                continue
            values_by_block[str(block_name)].append(numeric)
            last_value_by_block[str(block_name)] = numeric

    best_block_costs = {}
    if isinstance(best_row, dict):
        raw_best_costs = best_row.get("block_costs")
        if isinstance(raw_best_costs, dict):
            best_block_costs = raw_best_costs

    summary: dict[str, dict[str, Any]] = {}
    for block_cfg in cfg.model_calibration.objective_block:
        block_name = str(block_cfg.name)
        summary[block_name] = {
            **_summarize_numeric(values_by_block.get(block_name, [])),
            "metric": str(block_cfg.metric),
            "weight": float(block_cfg.weight),
            "normalize_cost": bool(block_cfg.normalize_cost),
            "best_value": _safe_float(best_block_costs.get(block_name)),
            "last_value": last_value_by_block.get(block_name),
        }
    return summary


def _summarize_hydraulic_parameterization(
    cfg: ModelCalibrationConfig,
) -> dict[str, dict[str, Any]]:
    """Group calibrated parameters by hydraulic property."""
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "parameter_names": [],
            "targets": [],
            "modes": [],
            "parameterizations": [],
            "lithology_keys": [],
        }
    )
    for parameter_cfg in cfg.model_calibration.parameter:
        property_name = parameter_cfg.property
        if property_name is None:
            continue
        group = grouped[str(property_name)]
        group["parameter_names"].append(str(parameter_cfg.name))
        group["targets"].append(str(parameter_cfg.target))
        group["modes"].append(str(parameter_cfg.mode))
        group["parameterizations"].append(str(parameter_cfg.parameterization))
        if parameter_cfg.lithology_key is not None:
            group["lithology_keys"].append(str(parameter_cfg.lithology_key))
    return dict(sorted(grouped.items()))


def build_calibration_report(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build a JSON-serializable calibration report payload."""
    history_rows = _load_iteration_history(session.iteration_history_path)
    best_row = _best_history_row(history_rows)
    objective_values = [
        value
        for row in history_rows
        if (value := _safe_float(row.get("objective_total"))) is not None
    ]
    finite_objective_values = [
        value for value in objective_values if math.isfinite(value)
    ]
    failed_iteration_count = sum(
        1 for row in history_rows if str(row.get("status")) != "objective_evaluated"
    )

    best_params = manifest.get("params_best")
    report = {
        "role": "model_calibration_report",
        "calibration_id": session.calibration_id,
        "status": manifest.get("status"),
        "method": manifest.get("method"),
        "paths": {
            "session_manifest": str(session.session_manifest_path),
            "iteration_history": (
                str(session.iteration_history_path)
                if session.iteration_history_path.is_file()
                else None
            ),
            "result": manifest.get("result_path"),
        },
        "best_model": {
            "cost_best": _safe_float(manifest.get("cost_best")),
            "score_best": _safe_float(manifest.get("score_best")),
            "params_best": (
                dict(best_params) if isinstance(best_params, dict) else best_params
            ),
            "best_iteration_id": (
                None if best_row is None else best_row.get("iteration_id")
            ),
        },
        "iterations": {
            "persisted_history": bool(
                cfg.model_calibration.persist_iteration_history
                and session.iteration_history_path.is_file()
            ),
            "detail_level": str(cfg.model_calibration.persist_iteration_detail_level),
            "count": int(manifest.get("iteration_count", 0)),
            "status_counts": _summarize_status_counts(history_rows),
            "failed_count": int(failed_iteration_count),
            "objective_total": {
                **_summarize_numeric(objective_values),
                "finite_count": int(len(finite_objective_values)),
                "infinite_or_nan_count": int(
                    len(objective_values) - len(finite_objective_values)
                ),
            },
        },
        "runtime": {
            "session_prepare_time_seconds": _safe_float(
                manifest.get("session_prepare_time_seconds")
            ),
            "candidate_run_count": int(manifest.get("candidate_run_count", 0)),
            "objective_cache_hit_count": int(
                manifest.get("objective_cache_hit_count", 0)
            ),
            "restored_evaluation_count": int(
                manifest.get("restored_evaluation_count", 0)
            ),
            "candidate_timing_summary": dict(
                manifest.get("candidate_timing_summary", {})
            ),
            "rerun_best_with_outputs": bool(
                cfg.model_calibration.rerun_best_with_outputs
            ),
            "persist_model_distribution": bool(
                cfg.model_calibration.persist_model_distribution
            ),
            "rerun_model_distribution_with_outputs": bool(
                cfg.model_calibration.rerun_model_distribution_with_outputs
            ),
            "objective_mapping_enabled": bool(
                cfg.model_calibration.objective_mapping.enabled
            ),
            "resume_existing_session": bool(
                cfg.model_calibration.resume_existing_session
            ),
            "reuse_persisted_iterations": bool(
                cfg.model_calibration.reuse_persisted_iterations
            ),
            "prepared_hydraulic_support": (
                None
                if session.prepared_hydraulic_support is None
                else session.prepared_hydraulic_support.to_summary()
            ),
        },
        "parameters": _summarize_parameter_history(
            cfg=cfg,
            rows=history_rows,
            best_params=best_params if isinstance(best_params, dict) else None,
        ),
        "blocks": _summarize_block_contributions(
            cfg=cfg,
            rows=history_rows,
            best_row=best_row,
        ),
        "hydraulic_parameterization": _summarize_hydraulic_parameterization(cfg),
        "diagnostics": {
            "best_rerun": manifest.get("best_rerun"),
            "model_distribution": manifest.get("model_distribution"),
            "model_distribution_rerun": manifest.get("model_distribution_rerun"),
            "objective_mapping": manifest.get("objective_mapping"),
        },
    }
    return report


def persist_calibration_report(
    *,
    session: PreparedCalibrationSession,
    cfg: ModelCalibrationConfig,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Write the calibration report and return a compact manifest summary."""
    report = build_calibration_report(
        session=session,
        cfg=cfg,
        manifest=manifest,
    )
    report_path = session.calibration_root / "calibration_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(report_path),
        "iteration_count": int(report["iterations"]["count"]),
        "failed_count": int(report["iterations"]["failed_count"]),
        "block_names": list(report["blocks"].keys()),
    }


__all__ = (
    "build_calibration_report",
    "persist_calibration_report",
)

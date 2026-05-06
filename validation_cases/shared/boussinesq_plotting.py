"""Plotting helpers for Boussinesq validation figures."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from validation_cases.shared.runtime import ValidationRunResult


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    return payload if isinstance(payload, dict) else None


def load_boussinesq_runtime_summary(result: ValidationRunResult) -> dict[str, Any] | None:
    """Load the persisted Boussinesq runtime summary when the run produced one."""
    candidates = [
        Path(result.model_ws) / "_boussinesq_summary.json",
        Path(result.postprocess_dir).parent / "_boussinesq_summary.json",
    ]
    for path in candidates:
        summary = _load_json(path)
        if summary is not None:
            return summary
    return None


def format_boussinesq_method_line(result: ValidationRunResult) -> str | None:
    """Return one compact method label suitable for figure footers."""
    solver_name = str(getattr(result, "solver_name", "") or "").strip().lower()
    if solver_name != "boussinesq" and "petsc" not in solver_name:
        return None

    summary = load_boussinesq_runtime_summary(result)
    if summary is None:
        if solver_name == "boussinesq":
            return "method=Boussinesq (runtime summary unavailable)"
        return None

    runtime_backend = str(summary.get("runtime_backend", "") or "").strip().lower()
    surface_model = str(
        summary.get("surface_interaction_model_resolved")
        or summary.get("surface_interaction_model_requested")
        or ""
    ).strip().lower()
    engine_id = str(summary.get("runtime_engine_id", "") or "").strip()

    if runtime_backend == "petsc" and surface_model == "vi_obstacle":
        return (
            "method=Boussinesq PETSc SNESVI head-only obstacle "
            "(steady pure, vi_obstacle)"
        )
    if runtime_backend == "petsc" and surface_model == "ts_vi_obstacle":
        return (
            "method=Boussinesq PETSc TS + SNESVI head-only obstacle "
            "(ts_vi_obstacle)"
        )
    if runtime_backend == "petsc" and surface_model == "complementarity":
        return "method=Boussinesq PETSc mixed complementarity"
    if runtime_backend == "petsc" and surface_model == "regularized_partition":
        return "method=Boussinesq PETSc regularized partition"
    if runtime_backend:
        suffix = f", {engine_id}" if engine_id else ""
        return f"method=Boussinesq {runtime_backend} ({surface_model or 'surface auto'}{suffix})"
    return None


def with_boussinesq_method_line(
    result: ValidationRunResult,
    lines: Iterable[str],
) -> list[str]:
    """Append the Boussinesq method line to one figure footer when available."""
    footer_lines = list(lines)
    method_line = format_boussinesq_method_line(result)
    if method_line:
        footer_lines.append(method_line)
    return footer_lines


__all__ = [
    "format_boussinesq_method_line",
    "load_boussinesq_runtime_summary",
    "with_boussinesq_method_line",
]

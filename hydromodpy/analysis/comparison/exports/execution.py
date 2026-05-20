"""Execution-time summary CSV export."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .base import (
    _completed_simulation_summaries,
    _runtime_seconds_with_scope,
    _write_csv,
)


def write_execution_summary_csv(
    *,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    reference_simulation: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write one flat solver runtime summary CSV.

    The comparison intentionally uses only the flow-solver execution time.
    Whole-workflow wall times include setup, data loading, meshing, extraction
    and report generation, so they are not comparable as solver timings.
    """
    rows: list[dict[str, Any]] = []
    reference_runtime: float | None = None
    reference_time_scope = ""
    for summary in _completed_simulation_summaries(simulation_summaries):
        if str(summary.get("id", "")) == reference_simulation:
            reference_runtime, reference_time_scope = _runtime_seconds_with_scope(summary)
            break

    for summary in _completed_simulation_summaries(simulation_summaries):
        runtime_seconds, time_scope = _runtime_seconds_with_scope(summary)
        if runtime_seconds is None:
            continue
        speedup = (
            reference_runtime / runtime_seconds
            if reference_runtime is not None and runtime_seconds > 0.0
            else math.nan
        )
        rows.append(
            {
                "simulation_id": summary.get("id", ""),
                "simulation_label": summary.get("label", summary.get("id", "")),
                "solver": summary.get("solver", ""),
                "mesh_mode": summary.get("mesh_mode", ""),
                "runtime_seconds": runtime_seconds,
                "runtime_minutes": runtime_seconds / 60.0,
                "time_scope": time_scope,
                "reference_simulation": reference_simulation or "",
                "reference_time_scope": reference_time_scope,
                "speedup_vs_reference": speedup,
            }
        )

    artifacts: list[dict[str, Any]] = []
    if rows:
        path = comparison_root / "execution_times.csv"
        _write_csv(
            path,
            rows,
            [
                "simulation_id",
                "simulation_label",
                "solver",
                "mesh_mode",
                "runtime_seconds",
                "runtime_minutes",
                "time_scope",
                "reference_simulation",
                "reference_time_scope",
                "speedup_vs_reference",
            ],
        )
        artifacts.append({"kind": "execution_times_csv", "path": str(path)})
    return artifacts, rows

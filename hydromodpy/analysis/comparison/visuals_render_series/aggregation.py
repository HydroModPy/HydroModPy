"""Time-axis and reduction helpers for comparison series visuals."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.visuals_style import (
    _display_simulation_label,
    _safe_float,
    _solver_color,
)

_SECONDS_PER_DAY = 86_400.0


def _rows_have_elapsed_seconds(rows: Iterable[Mapping[str, Any]]) -> bool:
    seen = False
    for row in rows:
        seen = True
        if _safe_float(row.get("elapsed_seconds")) is None:
            return False
    return seen


def _row_time_value(row: Mapping[str, Any], *, use_elapsed_seconds: bool) -> float | None:
    value = _safe_float(row.get("elapsed_seconds" if use_elapsed_seconds else "time_index"))
    if value is None:
        return None
    return value / _SECONDS_PER_DAY if use_elapsed_seconds else value


def _time_axis_label(*, use_elapsed_seconds: bool) -> str:
    return "Elapsed time [d]" if use_elapsed_seconds else "Time step"


def _surface_reference_lines(
    rows: Iterable[Mapping[str, Any]],
) -> list[tuple[str, str, float]]:
    """Return stable surface-elevation reference lines for point plots."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        top = _safe_float(row.get("surface_top_m"))
        if top is None:
            continue
        key = (
            str(row.get("simulation_id", "")),
            str(row.get("simulation_label", row.get("simulation_id", ""))),
        )
        grouped.setdefault(key, []).append(top)

    lines: list[tuple[str, str, float]] = []
    for (simulation_id, simulation_label), values in sorted(grouped.items()):
        finite = [value for value in values if math.isfinite(value)]
        if finite:
            lines.append((simulation_id, simulation_label, float(np.nanmedian(finite))))
    if len(lines) <= 1:
        return lines

    top_values = np.asarray([line[2] for line in lines], dtype=float)
    if np.nanmax(top_values) - np.nanmin(top_values) <= 0.05:
        # All simulations share the same surface. Keep a single reference line.
        return [("surface", "Surface", float(np.nanmedian(top_values)))]
    return lines


def _plot_surface_reference_lines(ax: Any, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for simulation_id, simulation_label, top in _surface_reference_lines(rows):
        if simulation_id == "surface":
            color = "#111827"
            label = "Surface"
        else:
            color = _solver_color(simulation_id)
            label = "Surface " + _display_simulation_label(
                simulation_id=simulation_id, simulation_label=simulation_label
            )
        ax.axhline(
            top,
            color=color,
            linestyle=(0, (5, 3)),
            linewidth=1.15,
            alpha=0.72,
            label=label,
            zorder=1,
        )
        count += 1
    return count


def _budget_time_field(rows: list[Mapping[str, Any]]) -> tuple[bool, str, str]:
    use_elapsed_seconds = all(_safe_float(row.get("elapsed_seconds")) is not None for row in rows)
    x_field = "elapsed_seconds" if use_elapsed_seconds else "time_index"
    return use_elapsed_seconds, x_field, _time_axis_label(use_elapsed_seconds=use_elapsed_seconds)


def _budget_component_points(
    budget_rows: list[Mapping[str, Any]],
    *,
    component: str,
    x_field: str,
    use_elapsed_seconds: bool,
) -> dict[tuple[str, str], list[tuple[float, float, float | None]]]:
    grouped: dict[tuple[str, str], list[tuple[float, float, float | None]]] = {}
    for row in budget_rows:
        if str(row.get("component", "")) != component:
            continue
        x_value = _safe_float(row.get(x_field))
        if x_value is not None and use_elapsed_seconds:
            x_value = x_value / _SECONDS_PER_DAY
        value = _safe_float(row.get("value"))
        if x_value is None or value is None:
            continue
        dt_seconds = None
        period_start = _safe_float(row.get("period_start_seconds"))
        period_end = _safe_float(row.get("period_end_seconds"))
        if period_start is not None and period_end is not None and period_end > period_start:
            dt_seconds = period_end - period_start
        simulation_id = str(row.get("simulation_id", ""))
        simulation_label = str(row.get("simulation_label", simulation_id))
        grouped.setdefault((simulation_id, simulation_label), []).append(
            (x_value, value, dt_seconds)
        )
    return grouped

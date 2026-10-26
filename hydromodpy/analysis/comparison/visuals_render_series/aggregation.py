"""Time-axis and reduction helpers for comparison series visuals."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hydromodpy.analysis.comparison.visuals_style import (
    _safe_float,
)
from hydromodpy.core.units.time import SECONDS_PER_DAY


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
    return value / SECONDS_PER_DAY if use_elapsed_seconds else value


def _time_axis_label(*, use_elapsed_seconds: bool) -> str:
    return "Elapsed time [d]" if use_elapsed_seconds else "Time step"


def _budget_time_field(rows: list[Mapping[str, Any]]) -> tuple[bool, str, str]:
    use_elapsed_seconds = all(_safe_float(row.get("elapsed_seconds")) is not None for row in rows)
    x_field = "elapsed_seconds" if use_elapsed_seconds else "time_index"
    return use_elapsed_seconds, x_field, _time_axis_label(use_elapsed_seconds=use_elapsed_seconds)


_BUDGET_ZONE_NAMES = {"domain": "model domain", "catchment": "delineated catchment"}


def _budget_zone_suffix(rows: Iterable[Mapping[str, Any]]) -> str:
    """Return `` (zone)`` naming the one zone the budget rows sum, empty when they do not say."""
    zones = {str(row.get("budget_zone", "")) for row in rows} - {""}
    if len(zones) != 1:
        return ""
    zone = zones.pop()
    return f" ({_BUDGET_ZONE_NAMES.get(zone, zone)})"


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
            x_value = x_value / SECONDS_PER_DAY
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

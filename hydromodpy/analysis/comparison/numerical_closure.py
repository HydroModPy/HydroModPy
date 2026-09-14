"""Post-run water-budget closure diagnostics for comparison reports."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.runtime.mesh import resolve_bundle_cells
from hydromodpy.analysis.comparison.runtime.metadata import open_result_store_for_write

CLOSURE_STATION_ID = "__global__"
CLOSURE_VARIABLE = "water_budget"

DETAIL_FIELDS = [
    "simulation_id",
    "simulation_label",
    "solver",
    "period_index",
    "elapsed_seconds",
    "closure_residual_m3_s",
    "abs_closure_residual_m3_s",
    "closure_residual_mm_d",
    "relative_closure_error",
    "diagnostic",
    "source",
]

SUMMARY_FIELDS = [
    "simulation_id",
    "simulation_label",
    "solver",
    "n_periods",
    "area_m2",
    "max_abs_closure_m3_s",
    "mean_abs_closure_m3_s",
    "rmse_closure_m3_s",
    "max_abs_closure_mm_d",
    "relative_closure_error_p95",
    "diagnostic",
]

METRIC_NAME_BY_FIELD = {
    "n_periods": "closure_n_periods",
    "max_abs_closure_m3_s": "closure_max_abs_m3_s",
    "mean_abs_closure_m3_s": "closure_mean_abs_m3_s",
    "rmse_closure_m3_s": "closure_rmse_m3_s",
    "max_abs_closure_mm_d": "closure_max_abs_mm_d",
    "relative_closure_error_p95": "closure_relative_error_p95",
}

_DIAGNOSTIC_CODE = {"OK": 0.0, "WARN": 1.0, "CHECK": 2.0}
_DERIVED_COMPONENTS = {
    "closure_residual_m3_s",
    "balance_implied_outflow_total_m3_s",
    "comparable_outflow_total_m3_s",
}


def write_numerical_closure_exports(
    *,
    comparison_root: Path,
    budget_rows: Iterable[Mapping[str, Any]],
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Write compact water-budget closure diagnostics and persist scalar metrics."""
    summaries = [dict(item) for item in simulation_summaries]
    detail_rows, summary_rows = build_numerical_closure_tables(
        budget_rows=budget_rows,
        simulation_summaries=summaries,
    )
    artifacts: list[dict[str, Any]] = []
    comparison_root.mkdir(parents=True, exist_ok=True)

    if detail_rows:
        detail_path = comparison_root / "numerical_closure_by_period.csv"
        _write_csv(detail_path, detail_rows, DETAIL_FIELDS)
        artifacts.append({"kind": "numerical_closure_by_period_csv", "path": str(detail_path)})

    if summary_rows:
        summary_path = comparison_root / "numerical_closure_summary.csv"
        _write_csv(summary_path, summary_rows, SUMMARY_FIELDS)
        artifacts.append({"kind": "numerical_closure_summary_csv", "path": str(summary_path)})
        json_path = comparison_root / "numerical_closure_summary.json"
        json_path.write_text(
            json.dumps(
                {
                    "schema_version": "numerical_closure_summary_v1",
                    "station_id": CLOSURE_STATION_ID,
                    "variable": CLOSURE_VARIABLE,
                    "summary": summary_rows,
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        artifacts.append({"kind": "numerical_closure_summary_json", "path": str(json_path)})

    _persist_closure_metrics(summary_rows, summaries)
    return artifacts, detail_rows, summary_rows


def build_numerical_closure_tables(
    *,
    budget_rows: Iterable[Mapping[str, Any]],
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build period and summary closure diagnostics from normalized budget rows."""
    summaries_by_id = {
        str(summary.get("id", "")): dict(summary)
        for summary in simulation_summaries
        if str(summary.get("id", ""))
    }
    areas_by_id = {
        simulation_id: _simulation_area_m2(summary)
        for simulation_id, summary in summaries_by_id.items()
    }
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in budget_rows:
        simulation_id = str(row.get("simulation_id", "")).strip()
        component = str(row.get("component", "")).strip()
        if not simulation_id or not component:
            continue
        value = _as_float(row.get("value"))
        if value is None:
            continue
        elapsed = _as_float(row.get("elapsed_seconds"))
        time_index = str(row.get("time_index", "")).strip()
        time_key = (
            f"elapsed_seconds:{elapsed:.12g}" if elapsed is not None else f"time_index:{time_index}"
        )
        item = grouped.setdefault(
            (simulation_id, time_key),
            {
                "template": dict(row),
                "components": {},
                "sort_value": (
                    elapsed if elapsed is not None else _as_float(time_index) or float(len(grouped))
                ),
            },
        )
        item["components"][component] = float(value)

    detail_rows: list[dict[str, Any]] = []
    for (simulation_id, _time_key), item in sorted(
        grouped.items(),
        key=lambda entry: (entry[0][0], float(entry[1].get("sort_value", 0.0)), entry[0][1]),
    ):
        components = dict(item["components"])
        closure, source = _closure_residual(components)
        if closure is None:
            continue
        denominator = _closure_denominator(components)
        relative = (
            abs(closure) / denominator
            if denominator is not None and denominator > 0.0
            else math.nan
        )
        area = areas_by_id.get(simulation_id)
        closure_mm_d = (
            (closure / area) * 86400.0 * 1000.0 if area is not None and area > 0.0 else math.nan
        )
        template = item["template"]
        detail_rows.append(
            {
                "simulation_id": simulation_id,
                "simulation_label": template.get(
                    "simulation_label",
                    summaries_by_id.get(simulation_id, {}).get("label", simulation_id),
                ),
                "solver": template.get(
                    "solver",
                    summaries_by_id.get(simulation_id, {}).get("solver", ""),
                ),
                "period_index": template.get("period_index", ""),
                "elapsed_seconds": template.get("elapsed_seconds", ""),
                "closure_residual_m3_s": closure,
                "abs_closure_residual_m3_s": abs(closure),
                "closure_residual_mm_d": closure_mm_d,
                "relative_closure_error": relative,
                "diagnostic": _diagnostic(relative, abs(closure_mm_d)),
                "source": source,
            }
        )

    summary_rows = _summary_rows(detail_rows, summaries_by_id, areas_by_id)
    return detail_rows, summary_rows


def _closure_residual(components: Mapping[str, float]) -> tuple[float | None, str]:
    direct = _finite_float(components.get("closure_residual_m3_s"))
    if direct is not None:
        return direct, "closure_residual_m3_s"
    if "recharge_total_m3_s" not in components or "storage_change_total_m3_s" not in components:
        return None, ""
    residual = (
        float(components.get("recharge_total_m3_s", 0.0))
        + float(components.get("well_total_m3_s", 0.0))
        + float(components.get("dry_deficit_total_m3_s", 0.0))
        - float(components.get("drainage_total_m3_s", 0.0))
        - float(components.get("surface_excess_total_m3_s", 0.0))
        - float(components.get("prescribed_head_out_total_m3_s", 0.0))
        - float(components.get("evapotranspiration_total_m3_s", 0.0))
        - float(components.get("storage_change_total_m3_s", 0.0))
    )
    return residual, "reconstructed_from_budget_components"


def _closure_denominator(components: Mapping[str, float]) -> float | None:
    values = [
        abs(float(value))
        for component, value in components.items()
        if component not in _DERIVED_COMPONENTS and _finite_float(value) is not None
    ]
    if not values:
        return None
    total = float(sum(values))
    return total if math.isfinite(total) and total > 0.0 else None


def _summary_rows(
    detail_rows: list[dict[str, Any]],
    summaries_by_id: Mapping[str, Mapping[str, Any]],
    areas_by_id: Mapping[str, float | None],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in detail_rows:
        grouped[str(row.get("simulation_id", ""))].append(row)

    rows: list[dict[str, Any]] = []
    for simulation_id, group in sorted(grouped.items()):
        residuals = np.asarray(
            [
                float(row["closure_residual_m3_s"])
                for row in group
                if _finite_float(row.get("closure_residual_m3_s")) is not None
            ],
            dtype=float,
        )
        if residuals.size == 0:
            continue
        abs_residuals = np.abs(residuals)
        relatives = _finite_array(row.get("relative_closure_error") for row in group)
        mm_d = _finite_array(row.get("closure_residual_mm_d") for row in group)
        p95_relative = float(np.nanpercentile(relatives, 95.0)) if relatives.size else math.nan
        max_abs_mm_d = float(np.nanmax(np.abs(mm_d))) if mm_d.size else math.nan
        summary = summaries_by_id.get(simulation_id, {})
        rows.append(
            {
                "simulation_id": simulation_id,
                "simulation_label": summary.get("label", simulation_id),
                "solver": summary.get("solver", ""),
                "n_periods": int(residuals.size),
                "area_m2": areas_by_id.get(simulation_id) or math.nan,
                "max_abs_closure_m3_s": float(np.nanmax(abs_residuals)),
                "mean_abs_closure_m3_s": float(np.nanmean(abs_residuals)),
                "rmse_closure_m3_s": float(np.sqrt(np.nanmean(residuals**2))),
                "max_abs_closure_mm_d": max_abs_mm_d,
                "relative_closure_error_p95": p95_relative,
                "diagnostic": _diagnostic(p95_relative, max_abs_mm_d),
            }
        )
    return rows


def _persist_closure_metrics(
    summary_rows: Iterable[Mapping[str, Any]],
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> None:
    summaries_by_id = {
        str(summary.get("id", "")): dict(summary)
        for summary in simulation_summaries
        if str(summary.get("id", ""))
    }
    for row in summary_rows:
        simulation_id = str(row.get("simulation_id", ""))
        summary = summaries_by_id.get(simulation_id)
        if not summary:
            continue
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_name = summary.get("run_name")
        store, sim_id = open_result_store_for_write(
            config_path,
            preferred_sim_id=None if preferred_sim_id in (None, "") else str(preferred_sim_id),
            preferred_name=None if preferred_name in (None, "") else str(preferred_name),
        )
        if store is None or sim_id in (None, ""):
            continue
        try:
            n_samples = int(float(row.get("n_periods", 0) or 0)) or None
            for field, metric_name in METRIC_NAME_BY_FIELD.items():
                value = _finite_float(row.get(field))
                if value is None:
                    continue
                store.write_metric(
                    sim_id,
                    CLOSURE_STATION_ID,
                    metric_name,
                    value,
                    variable=CLOSURE_VARIABLE,
                    n_samples=n_samples,
                )
            code = _DIAGNOSTIC_CODE.get(str(row.get("diagnostic", "")).upper())
            if code is not None:
                store.write_metric(
                    sim_id,
                    CLOSURE_STATION_ID,
                    "closure_status_code",
                    code,
                    variable=CLOSURE_VARIABLE,
                    n_samples=n_samples,
                )
        finally:
            try:
                store.close()
            except Exception:
                pass


def _simulation_area_m2(summary: Mapping[str, Any]) -> float | None:
    run_folder_raw = summary.get("run_folder")
    if run_folder_raw in (None, ""):
        return None
    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
    try:
        cells = resolve_bundle_cells(
            Path(str(run_folder_raw)),
            config_path=config_path,
            solver_name=str(summary.get("solver", "") or ""),
        )
    except Exception:
        return None
    if cells is None or cells.area_m2 is None:
        return None
    area = np.asarray(cells.area_m2, dtype=float).reshape(-1)
    area = area[np.isfinite(area) & (area > 0.0)]
    if area.size == 0:
        return None
    total = float(np.nansum(area))
    return total if math.isfinite(total) and total > 0.0 else None


def _diagnostic(relative_error: float, max_abs_mm_d: float) -> str:
    relative = _finite_float(relative_error)
    depth = _finite_float(max_abs_mm_d)
    if (relative is not None and relative <= 1.0e-3) or (depth is not None and depth <= 1.0e-3):
        return "OK"
    if (relative is not None and relative <= 1.0e-2) or (depth is not None and depth <= 1.0e-2):
        return "WARN"
    if relative is None and depth is None:
        return "UNKNOWN"
    return "CHECK"


def _finite_array(values: Iterable[Any]) -> np.ndarray:
    finite = [value for value in (_finite_float(value) for value in values) if value is not None]
    return np.asarray(finite, dtype=float)


def _finite_float(value: Any) -> float | None:
    number = _as_float(value)
    if number is None or not math.isfinite(number):
        return None
    return float(number)


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


__all__ = [
    "CLOSURE_STATION_ID",
    "CLOSURE_VARIABLE",
    "build_numerical_closure_tables",
    "write_numerical_closure_exports",
]

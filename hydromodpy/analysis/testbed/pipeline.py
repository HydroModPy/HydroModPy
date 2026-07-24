"""Compute steps for the testbed runtime (extraction, metric rows, manifests)."""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.testbed.config import (
    TestbedCaseConfig,
    TestbedConfig,
    TestbedMetricConfig,
)
from hydromodpy.analysis.testbed.io import _jsonable
from hydromodpy.core.logging import get_logger
from hydromodpy.results.derive.config_flags import log_missing_field

logger = get_logger(__name__)

RUNNER_WORKFLOWS = {
    "calibration": "calibration",
    "comparison": "comparison",
    "simulation": "simulation",
}
DEFAULT_RUNNER_METRICS = {
    "comparison": (
        TestbedMetricConfig(name="comparison_id", source="comparison_id", required=False),
        TestbedMetricConfig(name="audit_status", source="audit_status", required=False),
        TestbedMetricConfig(name="n_metric_rows", source="n_metric_rows", required=False),
        TestbedMetricConfig(name="n_difference_rows", source="n_difference_rows", required=False),
        TestbedMetricConfig(
            name="closure_max_abs_m3_s",
            source="closure_max_abs_m3_s",
            required=False,
        ),
        TestbedMetricConfig(
            name="closure_max_abs_mm_d",
            source="closure_max_abs_mm_d",
            required=False,
        ),
        TestbedMetricConfig(
            name="closure_relative_error_p95",
            source="closure_relative_error_p95",
            required=False,
        ),
        TestbedMetricConfig(
            name="closure_status_code",
            source="closure_status_code",
            required=False,
        ),
    ),
}


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    text = text.strip("._-")
    return text or "case"


def _lookup_metric_source(summary: Mapping[str, Any], source: str) -> Any:
    current: Any = summary
    for part in source.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _safe_number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        number = float(value)
        return number if math.isfinite(number) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _flatten_numeric_values(
    mapping: Mapping[str, Any],
    *,
    prefix: str = "",
) -> dict[str, float | int]:
    row: dict[str, float | int] = {}
    for key, value in mapping.items():
        metric_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            row.update(_flatten_numeric_values(value, prefix=metric_key))
            continue
        number = _safe_number(value)
        if number is not None:
            row[metric_key] = number
    return row


def _dataframe_is_empty(value: Any) -> bool:
    return value is None or bool(getattr(value, "empty", True))


def _series_numbers(series: Any) -> list[float]:
    values: list[float] = []
    try:
        iterable = series.dropna().tolist()
    except Exception:
        iterable = [] if series is None else list(series)
    for value in iterable:
        number = _safe_number(value)
        if number is not None:
            values.append(float(number))
    return values


def _numbers_stats(values: Sequence[float]) -> dict[str, float | int]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return {"count": 0}
    return {
        "count": len(finite),
        "min": min(finite),
        "max": max(finite),
        "mean": sum(finite) / len(finite),
        "abs_max": max(abs(value) for value in finite),
        "last": finite[-1],
    }


def _array_stats(value: Any) -> dict[str, float | int]:
    try:
        import numpy as np

        array = np.asarray(value, dtype=float)
        flat = array.reshape(-1)
        finite_mask = np.isfinite(flat)
        finite = flat[finite_mask]
        total_count = int(flat.size)
        finite_count = int(finite.size)
        stats: dict[str, float | int] = {
            "total_count": total_count,
            "finite_count": finite_count,
            "nodata_count": total_count - finite_count,
            "finite_fraction": (finite_count / total_count) if total_count else 0.0,
        }
        if finite_count:
            stats.update(
                {
                    "min": float(np.min(finite)),
                    "max": float(np.max(finite)),
                    "mean": float(np.mean(finite)),
                    "abs_max": float(np.max(np.abs(finite))),
                    "positive_sum": float(np.sum(finite[finite > 0.0])),
                    "negative_sum": float(np.sum(finite[finite < 0.0])),
                }
            )
        return stats
    except Exception:
        return {"total_count": 0, "finite_count": 0, "nodata_count": 0}


def _extract_catalog_metadata(run: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "sim_id",
        "name",
        "project",
        "solver",
        "solver_category",
        "flow_regime",
        "status",
        "duration_s",
        "n_cells",
        "n_layers",
        "n_timesteps",
    ):
        try:
            value = getattr(run, key)
        except Exception:
            continue
        if value is not None:
            metadata[key] = _jsonable(value)
    return metadata


def _ensure_mesh_process_payload(payload: dict[str, Any]) -> None:
    """Ensure one simulation child payload has an explicit mesh process."""
    simulation = payload.get("simulation")
    if not isinstance(simulation, dict):
        simulation = {}
        payload["simulation"] = simulation
    raw_processes = simulation.get("process")
    if raw_processes is None:
        processes: list[dict[str, Any]] = []
    elif isinstance(raw_processes, list):
        processes = list(raw_processes)
    else:
        raise ValueError("simulation.process must be a list when provided")
    if not processes:
        processes.append(
            {
                "id": "mesh_main",
                "type": "mesh",
                "backend": "catchment",
            }
        )
    simulation["process"] = processes


def _extract_parameter_metrics(run: Any) -> dict[str, float | int]:
    try:
        params = run.parameters
    except Exception:
        return {}
    if _dataframe_is_empty(params):
        return {}
    try:
        rows = params.reset_index().to_dict(orient="records")
    except Exception:
        return {}
    metrics: dict[str, float | int] = {}
    for row in rows:
        name = _safe_text(row.get("param_name"))
        if name is None:
            continue
        zone = _safe_text(row.get("zone_id"))
        number = _safe_number(row.get("value"))
        if number is None:
            continue
        metric_name = _slugify(name if zone in (None, "__global__") else f"{name}_{zone}")
        metrics[metric_name] = number
    return metrics


def _extract_mass_balance_metrics(run: Any) -> dict[str, float | int]:
    try:
        mass_balance = run.mass_balance
    except Exception:
        return {}
    if _dataframe_is_empty(mass_balance) or "percent_error" not in mass_balance:
        return {}
    stats = _numbers_stats(_series_numbers(mass_balance["percent_error"]))
    metrics: dict[str, float | int] = {
        "mass_balance_rows": stats.get("count", 0),
    }
    if stats.get("count", 0):
        metrics.update(
            {
                "max_abs_mass_balance_percent_error": stats["abs_max"],
                "mean_mass_balance_percent_error": stats["mean"],
                "last_mass_balance_percent_error": stats["last"],
            }
        )
    return metrics


def _extract_budget_metrics(run: Any) -> tuple[dict[str, Any], dict[str, float | int]]:
    try:
        budget = run.budget()
    except Exception:
        return {}, {}
    if (
        _dataframe_is_empty(budget)
        or "component" not in budget
        or "flux_in" not in budget
        or "flux_out" not in budget
    ):
        return {}, {}
    budget_summary: dict[str, Any] = {}
    flow_metrics: dict[str, float | int] = {}
    try:
        grouped = budget.groupby("component", dropna=False)
    except Exception:
        return {}, {}
    for raw_component, rows in grouped:
        component = _slugify(str(raw_component).lower())
        flux_in = sum(_series_numbers(rows["flux_in"]))
        flux_out = sum(_series_numbers(rows["flux_out"]))
        net = flux_in - flux_out
        budget_summary[component] = {
            "total_in": flux_in,
            "total_out": flux_out,
            "net": net,
            "rows": int(len(rows)),
        }
        flow_metrics[f"budget_{component}_total_in"] = flux_in
        flow_metrics[f"budget_{component}_total_out"] = flux_out
        flow_metrics[f"budget_{component}_net"] = net
    return budget_summary, flow_metrics


def _extract_field_metrics(run: Any) -> tuple[dict[str, Any], dict[str, float | int]]:
    field_summary: dict[str, Any] = {}
    flow_metrics: dict[str, float | int] = {}
    for variable in (
        "head",
        "watertable_depth",
        "outflow_drain",
        "accumulation_flux",
        "recharge_flux",
    ):
        try:
            if hasattr(run, "has_field") and not run.has_field(variable):
                log_missing_field(logger, run, variable, "testbed field metrics")
                continue
            values = run.field(variable, timestep=-1)
        except Exception:
            continue
        stats = _array_stats(values)
        field_summary[variable] = stats
        for key, value in stats.items():
            number = _safe_number(value)
            if number is not None:
                flow_metrics[f"{variable}_{key}"] = number
        if variable == "head" and {"min", "max"}.issubset(stats):
            flow_metrics["head_range_m"] = float(stats["max"]) - float(stats["min"])
    return field_summary, flow_metrics


def _extract_simulation_catalog_summary(
    *,
    config_path: Path | None,
    child_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect scalar flow evidence from a completed child simulation."""
    try:
        from hydromodpy.analysis.comparison.runtime.metadata import discover_result_store
    except Exception:
        return {}

    store = None
    try:
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=_safe_text(child_summary.get("sim_id")),
            preferred_name=_safe_text(child_summary.get("name")),
        )
        if store is None or sim_id in (None, ""):
            return {}
        run = store[str(sim_id)]
        catalog = _extract_catalog_metadata(run)
        parameters = _extract_parameter_metrics(run)
        mass_balance_metrics = _extract_mass_balance_metrics(run)
        budget, budget_metrics = _extract_budget_metrics(run)
        field_summary, field_metrics = _extract_field_metrics(run)
        flow_metrics: dict[str, Any] = {}
        for key in ("duration_s", "n_cells", "n_layers", "n_timesteps"):
            value = _safe_number(catalog.get(key))
            if value is not None:
                flow_metrics[key] = value
        flow_metrics.update({f"param_{key}": value for key, value in parameters.items()})
        flow_metrics.update(mass_balance_metrics)
        flow_metrics.update(budget_metrics)
        flow_metrics.update(field_metrics)
        return {
            "catalog": catalog,
            "parameters": parameters,
            "budget": budget,
            "mass_balance": mass_balance_metrics,
            "field_summary": field_summary,
            "flow_metrics": flow_metrics,
        }
    except Exception as exc:
        return {
            "catalog_extraction_error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


@dataclass(frozen=True)
class TestbedPlannedCase:
    """One materialized child configuration."""

    variant: TestbedCaseConfig
    config_path: Path | None
    status: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.variant.id,
            "case_label": self.variant.label,
            "axis": self.variant.axis or "",
            "enabled": self.variant.enabled,
            "status": self.status,
            "config_path": "" if self.config_path is None else str(self.config_path),
        }


@dataclass(frozen=True)
class TestbedExecution:
    """Execution outcome for one testbed case."""

    case: TestbedPlannedCase
    status: str
    duration_seconds: float | None
    summary: dict[str, Any]
    error: str | None = None

    def to_case_row(self, *, runner_type: str) -> dict[str, Any]:
        row = self.case.to_mapping()
        row.update(
            {
                "runner": runner_type,
                "status": self.status,
                "duration_seconds": self.duration_seconds,
                "error": self.error or "",
            }
        )
        for key in (
            "mode",
            "name",
            "sim_id",
            "run_id",
            "wall_time_seconds",
            "comparison_id",
            "comparison_root",
            "comparison_web_report",
            "comparison_report_md",
            "comparison_metrics_csv",
            "comparison_differences_csv",
            "comparison_metrics_json",
            "comparison_audit_json",
            "comparison_audit_md",
            "comparison_figures_dir",
            "observables_csv",
            "reference_simulation",
            "audit_status",
            "manifest_path",
            "n_observable_rows",
            "n_metric_rows",
            "n_difference_rows",
            "catalog",
            "mass_balance",
            "flow_metrics",
            "output_mesh",
            "output_summary_json",
            "output_exchange_bundle_dir",
            "output_figure",
            "output_figure_regional",
            "manifest_csv",
        ):
            if key in self.summary:
                row[key] = self.summary.get(key)
        return row


def _catalog_manifest_payload(cfg: TestbedConfig) -> dict[str, Any] | None:
    """Return a JSON-ready description of the optional testbed catalog contract."""
    if cfg.catalog is None:
        return None
    return {
        "path": str(cfg.catalog.path),
        "format": cfg.catalog.format,
        "id_field": cfg.catalog.id_field,
        "label_field": cfg.catalog.label_field,
        "axis_field": cfg.catalog.axis_field,
        "enabled_field": cfg.catalog.enabled_field,
        "tags_field": cfg.catalog.tags_field,
        "required_fields": list(cfg.catalog.required_fields),
        "path_fields": list(cfg.catalog.path_fields),
        "tag_separator": cfg.catalog.tag_separator,
        "field_equals": dict(cfg.catalog.field_equals),
        "tags": list(cfg.catalog.tags),
        "exclude_tags": list(cfg.catalog.exclude_tags),
        "include_disabled": cfg.catalog.include_disabled,
        "limit": cfg.catalog.limit,
        "source_manifest_path": (
            None
            if cfg.catalog.source_manifest_path is None
            else str(cfg.catalog.source_manifest_path)
        ),
        "source_manifest_output_key": cfg.catalog.source_manifest_output_key,
    }


def _catalog_case_manifest_payload(cfg: TestbedConfig) -> list[dict[str, Any]]:
    """Return JSON-ready catalog case-generation rules."""
    return [
        {
            "id_template": rule.id_template,
            "label_template": rule.label_template,
            "axis_template": rule.axis_template,
            "enabled": rule.enabled,
            "required_fields": list(rule.required_fields),
            "field_equals": dict(rule.field_equals),
            "tags": list(rule.tags),
            "exclude_tags": list(rule.exclude_tags),
            "limit": rule.limit,
            "overlay": _jsonable(rule.overlay),
        }
        for rule in cfg.catalog_cases
    ]


def _default_metric_row(summary: Mapping[str, Any]) -> dict[str, Any]:
    return _flatten_numeric_values(summary)


def _configured_metric_row(
    *,
    metrics: Sequence[TestbedMetricConfig],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for metric in metrics:
        value = _lookup_metric_source(summary, metric.source)
        if value is None and metric.required:
            raise ValueError(
                f"Required testbed metric '{metric.name}' could not be found at "
                f"source '{metric.source}'."
            )
        row[metric.name] = value
    return row


def _metric_row_for_execution(
    *,
    execution: TestbedExecution,
    metrics: Sequence[TestbedMetricConfig],
    runner_type: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case_id": execution.case.variant.id,
        "case_label": execution.case.variant.label,
        "axis": execution.case.variant.axis or "",
        "status": execution.status,
    }
    if execution.status == "ok":
        effective_metrics = metrics or DEFAULT_RUNNER_METRICS.get(runner_type, ())
        row.update(
            _configured_metric_row(metrics=effective_metrics, summary=execution.summary)
            if effective_metrics
            else _default_metric_row(execution.summary)
        )
    else:
        row["error"] = execution.error or ""
    return row


def _build_report(
    *,
    cfg: TestbedConfig,
    cases: Sequence[TestbedPlannedCase],
    executions: Sequence[TestbedExecution],
) -> str:
    execution_by_case = {item.case.variant.id: item for item in executions}
    ok_count = len([item for item in executions if item.status == "ok"])
    failed_count = len([item for item in executions if item.status == "failed"])
    pending_count = len(
        [
            case
            for case in cases
            if case.variant.enabled and case.variant.id not in execution_by_case
        ]
    )
    lines = [
        f"# Testbed Summary: {cfg.id}",
        "",
        f"- Subject: `{cfg.subject}`",
        f"- Purpose: `{cfg.purpose}`",
        f"- Runner: `{cfg.runner.type}`",
        f"- Execute: {bool(cfg.execute)}",
        f"- Cases: {len(cases)}",
        f"- Successful: {ok_count}",
        f"- Failed: {failed_count}",
        f"- Pending: {pending_count}",
        "",
        "## Cases",
        "",
        "| Case | Axis | Status | Duration (s) |",
        "| --- | --- | --- | ---: |",
    ]
    for case in cases:
        execution = execution_by_case.get(case.variant.id)
        status = case.status if execution is None else execution.status
        duration = (
            ""
            if execution is None or execution.duration_seconds is None
            else execution.duration_seconds
        )
        lines.append(f"| {case.variant.id} | {case.variant.axis or ''} | {status} | {duration} |")
    return "\n".join(lines) + "\n"

"""Runtime for method testbeds."""

from __future__ import annotations

import csv
import json
import math
import numbers
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.testbed.config import (
    TestbedConfig,
    TestbedMetricConfig,
    TestbedVariantConfig,
)
from hydromodpy.core.config.path_resolution import is_declared_absolute_path
from hydromodpy.core.config.toml_loader import load_toml_with_base_config, merge_toml_payloads

PATH_KEY_HINTS = ("path", "root", "dir", "folder", "file", "mask")
RUNNER_WORKFLOWS = {
    "mesh_catchment": "mesh",
    "simulation": "simulation",
}


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    text = text.strip("._-")
    return text or "variant"


def _jsonable(value: Any) -> Any:
    """Return a JSON-serializable representation of one value."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, numbers.Real):
        number = float(value)
        if math.isfinite(number):
            return repr(number)
        raise ValueError("Cannot render non-finite numeric TOML value")
    if isinstance(value, Path):
        return json.dumps(value.as_posix())
    if isinstance(value, str):
        return json.dumps(value.replace("\\", "/"))
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    if isinstance(value, tuple):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML scalar type: {type(value).__name__}")


def _is_mapping_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def _looks_like_path_key(key: str) -> bool:
    token = str(key).strip().strip("'\"").split(".")[-1].lower()
    if token == "base_config":
        return True
    return any(hint in token for hint in PATH_KEY_HINTS)


def _absolutize_relative_path_values(value: Any, *, source_dir: Path, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(child_key): _absolutize_relative_path_values(
                child_value,
                source_dir=source_dir,
                key=str(child_key),
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [
            _absolutize_relative_path_values(item, source_dir=source_dir, key=key)
            for item in value
        ]
    if not isinstance(value, str) or not _looks_like_path_key(key):
        return value
    if value.strip() in ("", "~") or "://" in value:
        return value
    declared_path = Path(value).expanduser()
    if is_declared_absolute_path(declared_path):
        return declared_path.as_posix()
    return (source_dir / declared_path).resolve().as_posix()


def _render_toml_mapping(
    mapping: Mapping[str, Any],
    *,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    lines: list[str] = []
    scalar_items: list[tuple[str, Any]] = []
    nested_items: list[tuple[str, Mapping[str, Any]]] = []
    array_items: list[tuple[str, list[Mapping[str, Any]]]] = []

    for raw_key, value in mapping.items():
        key = str(raw_key)
        if isinstance(value, Mapping):
            nested_items.append((key, value))
        elif _is_mapping_list(value):
            array_items.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        lines.append(f"{key} = {_toml_scalar(value)}")

    for key, value in nested_items:
        if lines and lines[-1] != "":
            lines.append("")
        section = ".".join((*prefix, key))
        lines.append(f"[{section}]")
        lines.extend(_render_toml_mapping(value, prefix=(*prefix, key)))

    for key, items in array_items:
        section = ".".join((*prefix, key))
        for item in items:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{section}]]")
            lines.extend(_render_toml_mapping(item, prefix=(*prefix, key)))
    return lines


def _write_toml_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _render_toml_mapping(payload)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=True, indent=2) + "\n")


def _collect_fieldnames(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key in seen:
                continue
            seen.add(key)
            fieldnames.append(key)
    return fieldnames


def _write_csv_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _collect_fieldnames(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        if not fieldnames:
            stream.write("")
            return
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(_jsonable(value), ensure_ascii=True)


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
        from hydromodpy.analysis.comparison.runtime import discover_result_store
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

    variant: TestbedVariantConfig
    config_path: Path | None
    status: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant.id,
            "variant_label": self.variant.label,
            "axis": self.variant.axis or "",
            "enabled": self.variant.enabled,
            "status": self.status,
            "config_path": "" if self.config_path is None else str(self.config_path),
        }


@dataclass(frozen=True)
class TestbedExecution:
    """Execution outcome for one testbed variant."""

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
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "variant_id": execution.case.variant.id,
        "variant_label": execution.case.variant.label,
        "axis": execution.case.variant.axis or "",
        "status": execution.status,
    }
    if execution.status == "ok":
        row.update(
            _configured_metric_row(metrics=metrics, summary=execution.summary)
            if metrics
            else _default_metric_row(execution.summary)
        )
    else:
        row["error"] = execution.error or ""
    return row


class TestbedLauncher:
    """Expand variants, run child workflows, and collect testbed evidence."""

    def __init__(self, config_path: str | Path) -> None:
        self.cfg = TestbedConfig.from_file(config_path)

    @property
    def generated_configs_dir(self) -> Path:
        return self.cfg.output_root / "_generated_configs"

    def _base_config_path(self) -> Path:
        return self.cfg.base_config_path or self.cfg.config_path

    def _child_workflow(self) -> str:
        return RUNNER_WORKFLOWS[self.cfg.runner.type]

    def _base_child_payload(self) -> dict[str, Any]:
        base_config_path = self._base_config_path()
        payload = load_toml_with_base_config(base_config_path)
        payload = _absolutize_relative_path_values(
            payload,
            source_dir=base_config_path.parent,
        )
        if not isinstance(payload, dict):
            raise ValueError("testbed base config must load to a TOML mapping")
        payload.pop("testbed", None)
        payload["workflow"] = self._child_workflow()
        return payload

    def _materialize_child_config(self, variant: TestbedVariantConfig) -> Path:
        overlay = _absolutize_relative_path_values(
            variant.overlay,
            source_dir=self.cfg.base_dir,
        )
        payload = merge_toml_payloads(self._base_child_payload(), overlay)
        payload["workflow"] = self._child_workflow()
        path = self.generated_configs_dir / f"{_slugify(variant.id)}.toml"
        _write_toml_payload(path, payload)
        return path

    def build_plan(self) -> list[TestbedPlannedCase]:
        """Materialize child configs and return planned cases."""
        cases: list[TestbedPlannedCase] = []
        for variant in self.cfg.variants:
            if not variant.enabled:
                cases.append(TestbedPlannedCase(variant=variant, config_path=None, status="disabled"))
                continue
            cases.append(
                TestbedPlannedCase(
                    variant=variant,
                    config_path=self._materialize_child_config(variant),
                    status="planned",
                )
            )
        return cases

    def _run_case(self, case: TestbedPlannedCase) -> dict[str, Any]:
        if case.config_path is None:
            return {}
        if self.cfg.runner.type == "mesh_catchment":
            from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

            return dict(MeshCatchmentLauncher(case.config_path).run())
        if self.cfg.runner.type == "simulation":
            from hydromodpy._cli.workflows import run_simulation

            return dict(
                run_simulation(
                    case.config_path,
                    no_display=self.cfg.runner.no_display,
                )
            )
        raise ValueError(f"Unsupported testbed runner: {self.cfg.runner.type}")

    def _summary_paths(self) -> dict[str, str]:
        return {
            "plan_json": str((self.cfg.output_root / "testbed_plan.json").resolve()),
            "manifest_json": str((self.cfg.output_root / "testbed_manifest.json").resolve()),
            "cases_csv": str((self.cfg.output_root / "testbed_cases.csv").resolve()),
            "metrics_csv": str((self.cfg.output_root / "testbed_metrics.csv").resolve()),
            "report_markdown": str((self.cfg.output_root / "testbed_report.md").resolve()),
            "generated_configs_dir": str(self.generated_configs_dir.resolve()),
        }

    def _build_report(
        self,
        *,
        cases: Sequence[TestbedPlannedCase],
        executions: Sequence[TestbedExecution],
    ) -> str:
        execution_by_variant = {item.case.variant.id: item for item in executions}
        ok_count = len([item for item in executions if item.status == "ok"])
        failed_count = len([item for item in executions if item.status == "failed"])
        pending_count = len(
            [
                case
                for case in cases
                if case.variant.enabled and case.variant.id not in execution_by_variant
            ]
        )
        lines = [
            f"# Testbed Summary: {self.cfg.id}",
            "",
            f"- Subject: `{self.cfg.subject}`",
            f"- Purpose: `{self.cfg.purpose}`",
            f"- Runner: `{self.cfg.runner.type}`",
            f"- Execute: {bool(self.cfg.execute)}",
            f"- Variants: {len(cases)}",
            f"- Successful: {ok_count}",
            f"- Failed: {failed_count}",
            f"- Pending: {pending_count}",
            "",
            "## Variants",
            "",
            "| Variant | Axis | Status | Duration (s) |",
            "| --- | --- | --- | ---: |",
        ]
        for case in cases:
            execution = execution_by_variant.get(case.variant.id)
            status = case.status if execution is None else execution.status
            duration = "" if execution is None or execution.duration_seconds is None else execution.duration_seconds
            lines.append(
                f"| {case.variant.id} | {case.variant.axis or ''} | {status} | {duration} |"
            )
        return "\n".join(lines) + "\n"

    def _persist_outputs(
        self,
        *,
        cases: Sequence[TestbedPlannedCase],
        executions: Sequence[TestbedExecution],
    ) -> dict[str, str]:
        self.cfg.output_root.mkdir(parents=True, exist_ok=True)
        paths = self._summary_paths()
        _write_json(
            Path(paths["plan_json"]),
            {
                "schema_version": "testbed_plan_v1",
                "testbed_id": self.cfg.id,
                "subject": self.cfg.subject,
                "purpose": self.cfg.purpose,
                "runner": self.cfg.runner.type,
                "base_config": str(self._base_config_path()),
                "cases": [case.to_mapping() for case in cases],
            },
        )
        case_rows: list[dict[str, Any]] = []
        execution_by_variant = {item.case.variant.id: item for item in executions}
        for case in cases:
            execution = execution_by_variant.get(case.variant.id)
            if execution is None:
                row = case.to_mapping()
                row["runner"] = self.cfg.runner.type
                case_rows.append(row)
            else:
                case_rows.append(execution.to_case_row(runner_type=self.cfg.runner.type))
        _write_csv_rows(Path(paths["cases_csv"]), case_rows)

        metric_rows = [
            _metric_row_for_execution(execution=execution, metrics=self.cfg.metrics)
            for execution in executions
        ]
        _write_csv_rows(Path(paths["metrics_csv"]), metric_rows)
        _write_json(
            Path(paths["manifest_json"]),
            {
                "schema_version": "testbed_manifest_v1",
                "testbed_id": self.cfg.id,
                "subject": self.cfg.subject,
                "purpose": self.cfg.purpose,
                "runner": self.cfg.runner.type,
                "output_root": str(self.cfg.output_root),
                "execute": bool(self.cfg.execute),
                "variant_count": len(cases),
                "executed_count": len(executions),
                "successful_count": len([item for item in executions if item.status == "ok"]),
                "failed_count": len([item for item in executions if item.status == "failed"]),
                "cases": case_rows,
                "metrics": metric_rows,
                "paths": paths,
            },
        )
        Path(paths["report_markdown"]).write_text(
            self._build_report(cases=cases, executions=executions),
            encoding="utf-8",
        )
        return paths

    def run(self) -> dict[str, Any]:
        """Execute the testbed and return a compact summary."""
        cases = self.build_plan()
        executions: list[TestbedExecution] = []
        paths = self._persist_outputs(cases=cases, executions=executions)

        if self.cfg.execute:
            for case in cases:
                if case.status == "disabled":
                    continue
                started_at = time.perf_counter()
                try:
                    child_summary = self._run_case(case)
                    if self.cfg.runner.type == "simulation":
                        child_summary = {
                            **child_summary,
                            **_extract_simulation_catalog_summary(
                                config_path=case.config_path,
                                child_summary=child_summary,
                            ),
                        }
                    duration = round(float(time.perf_counter() - started_at), 6)
                    execution = TestbedExecution(
                        case=case,
                        status="ok",
                        duration_seconds=duration,
                        summary=_jsonable(child_summary),
                    )
                    if self.cfg.metrics:
                        _configured_metric_row(metrics=self.cfg.metrics, summary=execution.summary)
                    executions.append(execution)
                except Exception as exc:
                    duration = round(float(time.perf_counter() - started_at), 6)
                    executions.append(
                        TestbedExecution(
                            case=case,
                            status="failed",
                            duration_seconds=duration,
                            summary={},
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
                    paths = self._persist_outputs(cases=cases, executions=executions)
                    if not self.cfg.continue_on_error:
                        raise
                else:
                    paths = self._persist_outputs(cases=cases, executions=executions)

        successful_count = len([item for item in executions if item.status == "ok"])
        failed_count = len([item for item in executions if item.status == "failed"])
        return {
            "testbed_id": self.cfg.id,
            "subject": self.cfg.subject,
            "purpose": self.cfg.purpose,
            "runner": self.cfg.runner.type,
            "output_root": str(self.cfg.output_root),
            "variant_count": len(cases),
            "executed_count": len(executions),
            "successful_count": successful_count,
            "failed_count": failed_count,
            **paths,
        }

"""Child-launcher subprocess execution helpers for the regional-lab family."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.analysis.batch.batch_types import (
    RegionalLabPlannedCase,
    _normalize_text,
)


def _read_json_file_if_exists(path: Path) -> dict[str, Any] | None:
    """Load one JSON file when it exists and is valid."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return dict(payload)


def _safe_float(value: object) -> float | None:
    """Return one finite float or ``None`` when unavailable."""
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _extract_simulation_child_artifacts(config_path: Path) -> dict[str, Any]:
    """Extract compact simulation artifacts from one child launcher config."""
    from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
    from hydromodpy.core.workspace.path_registry import WorkspacePathRegistry

    artifacts: dict[str, Any] = {
        "child_artifact_kind": "simulation",
        "child_artifact_status": "unavailable",
    }
    try:
        cfg = get_root_config_provider().from_toml(config_path)
    except Exception as exc:
        artifacts["child_artifact_status"] = "config_parse_failed"
        artifacts["child_artifact_error_type"] = type(exc).__name__
        artifacts["child_artifact_error_message"] = str(exc)
        return artifacts

    paths = WorkspacePathRegistry.from_config(cfg.workspace)
    run_id = str(cfg.simulation.run_id or config_path.stem)
    run_folder = paths.run_folder(run_id).resolve()
    simulations_root = paths.solver_scratch_folder.resolve()
    artifacts.update(
        {
            "child_artifact_status": "resolved",
            "child_project_root": str(paths.project_root.resolve()),
            "child_output_root": str(paths._effective_output_root.resolve()),
            "child_run_id": run_id,
            "child_run_folder": str(run_folder),
        }
    )

    metrics_path = run_folder / "_metrics.json"
    metrics_payload = _read_json_file_if_exists(metrics_path)
    if metrics_payload is not None:
        artifacts["child_metrics_json"] = str(metrics_path.resolve())
        artifacts["child_wall_time_seconds"] = _safe_float(metrics_payload.get("wall_time_seconds"))
        artifacts["child_success"] = metrics_payload.get("success")
        artifacts["child_mesh_output_mesh"] = _normalize_text(
            metrics_payload.get("mesh_output_mesh")
        )
        artifacts["child_mesh_output_exchange_bundle_dir"] = _normalize_text(
            metrics_payload.get("mesh_output_exchange_bundle_dir")
        )

    summary_candidates = sorted(
        simulations_root.rglob("_boussinesq_summary.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if summary_candidates:
        summary_path = summary_candidates[0]
        summary_payload = _read_json_file_if_exists(summary_path)
        if summary_payload is not None:
            artifacts["child_boussinesq_summary_json"] = str(summary_path.resolve())
            artifacts["child_runtime_backend"] = _normalize_text(
                summary_payload.get("runtime_backend")
            )
            artifacts["child_runtime_engine"] = _normalize_text(
                summary_payload.get("runtime_engine")
            )
            artifacts["child_n_cells"] = summary_payload.get("n_cells")
            artifacts["child_solve_stage"] = _normalize_text(summary_payload.get("solve_stage"))
            artifacts["child_steady_residual_norm_inf"] = _safe_float(
                summary_payload.get("steady_residual_norm_inf")
            )
            artifacts["child_steady_nonlinear_iterations"] = summary_payload.get(
                "steady_nonlinear_iterations"
            )
            artifacts["child_surface_peak_active_fraction"] = _safe_float(
                summary_payload.get("surface_threshold_peak_active_fraction")
            )
            artifacts["child_surface_final_total_m3_day"] = _safe_float(
                summary_payload.get("surface_threshold_final_total_m3_day")
            )

    return artifacts


def _extract_comparison_output_artifacts(
    *,
    comparison_root: Path,
    child_kind: str,
) -> dict[str, Any]:
    """Extract compact comparison artifacts from one resolved output folder."""
    resolved_root = comparison_root.resolve()
    artifacts: dict[str, Any] = {
        "child_artifact_kind": child_kind,
        "child_artifact_status": "resolved",
        "child_comparison_root": str(resolved_root),
    }

    manifest_path = resolved_root / "comparison_manifest.json"
    manifest_payload = _read_json_file_if_exists(manifest_path)
    if manifest_payload is not None:
        artifacts["child_comparison_manifest_json"] = str(manifest_path.resolve())
        artifacts["child_wall_time_seconds"] = _safe_float(
            manifest_payload.get("wall_time_seconds")
        )
        artifacts["child_comparison_id"] = _normalize_text(manifest_payload.get("comparison_id"))
        artifacts["child_reference_simulation"] = _normalize_text(
            manifest_payload.get("reference_simulation")
        )
        artifacts["child_n_metric_rows"] = manifest_payload.get("n_metric_rows")
        artifacts["child_n_difference_rows"] = manifest_payload.get("n_difference_rows")
        artifacts["child_n_observable_rows"] = manifest_payload.get("n_observable_rows")
        simulations = manifest_payload.get("simulations")
        if isinstance(simulations, list):
            completed_count = 0
            failed_count = 0
            for item in simulations:
                if not isinstance(item, Mapping):
                    continue
                status = str(item.get("status", "")).strip().lower()
                if status in {"completed", "ok", "success"}:
                    completed_count += 1
                if status in {
                    "failed",
                    "error",
                    "run_failed",
                    "observable_extraction_failed",
                }:
                    failed_count += 1
            artifacts["child_simulation_count"] = len(simulations)
            artifacts["child_completed_simulation_count"] = completed_count
            artifacts["child_failed_simulation_count"] = failed_count

    metrics_path = resolved_root / "comparison_metrics.json"
    metrics_payload = _read_json_file_if_exists(metrics_path)
    if metrics_payload is not None:
        artifacts["child_comparison_metrics_json"] = str(metrics_path.resolve())
        summary_rows = metrics_payload.get("summary")
        differences_rows = metrics_payload.get("differences")
        if isinstance(summary_rows, list):
            rmse_values = [
                value
                for item in summary_rows
                if isinstance(item, Mapping)
                and (value := _safe_float(item.get("rmse"))) is not None
            ]
            mae_values = [
                value
                for item in summary_rows
                if isinstance(item, Mapping) and (value := _safe_float(item.get("mae"))) is not None
            ]
            artifacts["child_summary_metric_row_count"] = len(summary_rows)
            artifacts["child_summary_max_rmse"] = None if not rmse_values else max(rmse_values)
            artifacts["child_summary_max_mae"] = None if not mae_values else max(mae_values)
        if isinstance(differences_rows, list):
            artifacts["child_difference_metric_row_count"] = len(differences_rows)

    return artifacts


def _extract_comparison_child_artifacts(config_path: Path) -> dict[str, Any]:
    """Extract compact comparison artifacts from one child launcher config."""
    from hydromodpy.analysis.comparison.config import ComparisonConfig
    from hydromodpy.analysis.comparison.experiment_config import (
        SimulationComparisonConfig,
    )
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    artifacts: dict[str, Any] = {
        "child_artifact_kind": "comparison",
        "child_artifact_status": "unavailable",
    }
    try:
        payload = load_toml_with_base_config(config_path)
        section = payload.get("comparison")
        if not isinstance(section, Mapping):
            raise ValueError("[comparison] must be a mapping")
        if "variant" in section:
            cfg = ComparisonConfig.from_toml(payload, config_path=config_path)
        else:
            cfg = SimulationComparisonConfig.from_toml(payload, config_path=config_path)
    except Exception as exc:
        artifacts["child_artifact_status"] = "config_parse_failed"
        artifacts["child_artifact_error_type"] = type(exc).__name__
        artifacts["child_artifact_error_message"] = str(exc)
        return artifacts

    return _extract_comparison_output_artifacts(
        comparison_root=cfg.comparison_root,
        child_kind="comparison",
    )


def _extract_child_case_artifacts(case: RegionalLabPlannedCase) -> dict[str, Any]:
    """Extract launcher-specific child artifacts for one planned case."""
    if case.launcher == "simulation":
        return _extract_simulation_child_artifacts(case.config_path)
    if case.launcher == "comparison":
        return _extract_comparison_child_artifacts(case.config_path)
    return {
        "child_artifact_kind": case.launcher,
        "child_artifact_status": "unsupported_launcher",
    }

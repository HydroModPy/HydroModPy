"""Supplemental CSV exports for comparison runs."""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

HYDROGRAPHIC_NETWORK_METRICS_FIELDS = [
    "comparison_id",
    "simulation_id",
    "simulation_label",
    "solver",
    "mesh_label",
    "mesh_mode",
    "sim_id",
    "run_name",
    "run_folder",
    "reference_role",
    "candidate_role",
    "reference_feature_name",
    "candidate_feature_name",
    "tolerance_m",
    "crs",
    "reference_segment_count",
    "candidate_segment_count",
    "reference_matched_segment_count",
    "reference_missing_segment_count",
    "candidate_matched_segment_count",
    "candidate_extra_segment_count",
    "reference_total_length_m",
    "candidate_total_length_m",
    "matched_reference_length_m",
    "matched_candidate_length_m",
    "missing_reference_length_m",
    "extra_candidate_length_m",
    "reference_coverage_ratio",
    "candidate_match_ratio",
    "missing_reference_ratio",
    "extra_candidate_ratio",
    "length_balance_ratio",
    "length_f1_ratio",
    "hausdorff_distance_m",
]

CELL_FIELD_ACTIVE_METRICS_FIELDS = [
    "comparison_id",
    "simulation_id",
    "simulation_label",
    "solver",
    "mesh_label",
    "mesh_mode",
    "sim_id",
    "run_name",
    "run_folder",
    "source_variable",
    "threshold",
    "persistence_threshold",
    "n_timesteps",
    "catchment_cell_count",
    "active_cell_count_mean",
    "active_cell_count_max",
    "active_cell_count_last",
    "active_cell_count_any",
    "persistent_cell_count",
    "always_active_cell_count",
    "perennial_cell_count",
    "drainage_density_mean_pct",
    "drainage_density_max_pct",
    "drainage_density_last_pct",
    "active_any_ratio",
    "persistent_ratio",
    "always_active_ratio",
    "perennial_ratio",
    "persistence_mean",
    "persistence_max",
]

CELL_FIELD_NETWORK_OVERLAP_METRICS_FIELDS = [
    "comparison_id",
    "simulation_id",
    "simulation_label",
    "solver",
    "mesh_label",
    "mesh_mode",
    "sim_id",
    "run_name",
    "run_folder",
    "network_role",
    "source_variable",
    "threshold",
    "mode",
    "persistence_threshold",
    "timestep",
    "buffer_m",
    "catchment_cell_count",
    "active_cell_count",
    "network_cell_count",
    "overlap_cell_count",
    "missing_network_cell_count",
    "extra_active_cell_count",
    "network_coverage_ratio",
    "active_precision_ratio",
    "cell_f1_ratio",
    "cell_jaccard_ratio",
]

CELL_FIELD_NETWORK_DISTANCE_METRICS_FIELDS = [
    "comparison_id",
    "simulation_id",
    "simulation_label",
    "solver",
    "mesh_label",
    "mesh_mode",
    "sim_id",
    "run_name",
    "run_folder",
    "network_role",
    "source_variable",
    "threshold",
    "mode",
    "persistence_threshold",
    "timestep",
    "network_buffer_m",
    "distance_method",
    "catchment_cell_count",
    "active_cell_count",
    "network_cell_count",
    "sim_to_network_sample_count",
    "sim_to_network_distance_mean_m",
    "sim_to_network_distance_median_m",
    "sim_to_network_distance_p95_m",
    "sim_to_network_distance_max_m",
    "network_to_sim_sample_count",
    "network_to_sim_distance_mean_m",
    "network_to_sim_distance_median_m",
    "network_to_sim_distance_p95_m",
    "network_to_sim_distance_max_m",
    "bidirectional_distance_mean_m",
    "bidirectional_distance_quadratic_mean_m",
    "bidirectional_distance_absolute_difference_m",
    "planar_distance_ratio",
    "planar_distance_log10_ratio",
]

RELEASE_FLUX_NETWORK_OVERLAP_METRICS_FIELDS = CELL_FIELD_NETWORK_OVERLAP_METRICS_FIELDS
RELEASE_FLUX_NETWORK_DISTANCE_METRICS_FIELDS = CELL_FIELD_NETWORK_DISTANCE_METRICS_FIELDS


def _as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _slug_token(value: Any) -> str:
    token = str(value).strip().lower()
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in token)
    return "_".join(part for part in cleaned.split("_") if part) or "simulation"


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _completed_simulation_summaries(
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(summary)
        for summary in simulation_summaries
        if str(summary.get("status", "")) in {"completed", "reused"}
    ]


def _runtime_seconds(summary: Mapping[str, Any]) -> float | None:
    return _runtime_seconds_with_scope(summary)[0]


def _runtime_seconds_with_scope(summary: Mapping[str, Any]) -> tuple[float | None, str]:
    metrics = summary.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    run_metadata = summary.get("run_metadata")
    run_metadata_map = run_metadata if isinstance(run_metadata, Mapping) else {}
    boussinesq_summary = summary.get("boussinesq_summary")
    boussinesq_map = boussinesq_summary if isinstance(boussinesq_summary, Mapping) else {}
    for candidate in (
        summary.get("flow_solve_time_seconds"),
        metrics_map.get("flow_solve_time_seconds"),
        run_metadata_map.get("flow_solve_time_seconds"),
        boussinesq_map.get("flow_solve_time_seconds"),
    ):
        value = _as_float(candidate)
        if value is not None:
            return value, "flow_solve"
    return None, ""


def _observable_support_lookup(
    observables: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for observable in observables:
        lookup[str(observable.get("name", ""))] = str(observable.get("support", ""))
    return lookup


def _observable_variable_lookup(
    observables: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for observable in observables:
        lookup[str(observable.get("name", ""))] = str(observable.get("variable", ""))
    return lookup

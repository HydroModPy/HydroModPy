"""Supplemental CSV exports for method-comparison runs."""

from __future__ import annotations

import csv
import json
import logging
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.analysis.comparison.runtime import resolve_bundle_cells
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.core.units.scalar import parse_scalar_and_unit
from hydromodpy.core.units.volumetric_flow import factor_to_m3_per_s
from hydromodpy.physics.flow.history_contract import build_transient_time_axes

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog

logger = logging.getLogger(__name__)

HYDROGRAPHIC_NETWORK_METRICS_FIELDS = [
    "comparison_id",
    "variant_id",
    "variant_label",
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

SIMULATED_ACTIVE_NETWORK_METRICS_FIELDS = [
    "comparison_id",
    "variant_id",
    "variant_label",
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

SIMULATED_ACTIVE_NETWORK_OVERLAP_METRICS_FIELDS = [
    "comparison_id",
    "variant_id",
    "variant_label",
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

SIMULATED_ACTIVE_NETWORK_DISTANCE_METRICS_FIELDS = [
    "comparison_id",
    "variant_id",
    "variant_label",
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
    "bidirectional_distance_absolute_balance_m",
    "planar_distance_balance_ratio",
    "planar_distance_log10_balance",
]


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


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _completed_variant_summaries(
    variant_summaries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(summary)
        for summary in variant_summaries
        if str(summary.get("status", "")) in {"completed", "reused"}
    ]


def _runtime_seconds(summary: Mapping[str, Any]) -> float | None:
    for candidate in (
        summary.get("wall_time_seconds"),
        summary.get("metrics", {}).get("wall_time_seconds"),
        summary.get("run_metadata", {}).get("wall_time_seconds"),
    ):
        value = _as_float(candidate)
        if value is not None:
            return value
    return None


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


def write_observable_chronicle_exports(
    *,
    comparison_root: Path,
    rows: list[dict[str, Any]],
    detail_metrics: list[dict[str, Any]],
    observables: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Write CSV exports for non-map observables."""
    support_lookup = _observable_support_lookup(observables)
    variable_lookup = _observable_variable_lookup(observables)

    long_rows = [
        {
            "comparison_id": row.get("comparison_id", ""),
            "observable": row.get("observable", ""),
            "variable": variable_lookup.get(str(row.get("observable", "")), ""),
            "support": row.get("support", ""),
            "unit": row.get("unit", ""),
            "variant_id": row.get("variant_id", ""),
            "variant_label": row.get("variant_label", ""),
            "comparison_time_key": row.get("comparison_time_key", ""),
            "time": row.get("time", ""),
            "time_index": row.get("time_index", ""),
            "elapsed_seconds": row.get("elapsed_seconds", ""),
            "value_index": row.get("value_index", ""),
            "value": row.get("value", ""),
            "surface_top_m": row.get("surface_top_m", ""),
            "surface_bottom_m": row.get("surface_bottom_m", ""),
        }
        for row in rows
        if str(row.get("support", "")) != "map"
        and str(row.get("comparison_time_key", "")) != "reduced"
        and _as_float(row.get("value")) is not None
    ]

    wide_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in long_rows:
        key = (
            str(row.get("observable", "")),
            str(row.get("unit", "")),
            str(row.get("comparison_time_key", "")),
            str(row.get("value_index", "")),
        )
        item = wide_index.setdefault(
            key,
            {
                "comparison_id": row.get("comparison_id", ""),
                "observable": row.get("observable", ""),
                "variable": row.get("variable", ""),
                "support": row.get("support", ""),
                "unit": row.get("unit", ""),
                "comparison_time_key": row.get("comparison_time_key", ""),
                "time": row.get("time", ""),
                "time_index": row.get("time_index", ""),
                "elapsed_seconds": row.get("elapsed_seconds", ""),
                "value_index": row.get("value_index", ""),
            },
        )
        item[f"value__{row['variant_id']}"] = row.get("value", "")
    wide_rows = list(wide_index.values())

    delta_rows = [
        {
            "comparison_id": row.get("comparison_id", ""),
            "observable": row.get("observable", ""),
            "variable": variable_lookup.get(str(row.get("observable", "")), ""),
            "support": support_lookup.get(str(row.get("observable", "")), ""),
            "variant_id": row.get("variant_id", ""),
            "reference_variant": row.get("reference_variant", ""),
            "comparison_time_key": row.get("comparison_time_key", ""),
            "time": row.get("time", ""),
            "time_index": row.get("time_index", ""),
            "elapsed_seconds": row.get("elapsed_seconds", ""),
            "value_index": row.get("value_index", ""),
            "value": row.get("value", ""),
            "reference_value": row.get("reference_value", ""),
            "signed_error": row.get("signed_error", ""),
            "absolute_error": row.get("absolute_error", ""),
            "relative_error": row.get("relative_error", ""),
            "unit": row.get("unit", ""),
        }
        for row in detail_metrics
        if support_lookup.get(str(row.get("observable", "")), "") != "map"
    ]

    artifacts: list[dict[str, Any]] = []
    if long_rows:
        path = comparison_root / "timeseries_long.csv"
        _write_csv(
            path,
            long_rows,
            [
                "comparison_id",
                "observable",
                "variable",
                "support",
                "unit",
                "variant_id",
                "variant_label",
                "comparison_time_key",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
                "value",
                "surface_top_m",
                "surface_bottom_m",
            ],
        )
        artifacts.append({"kind": "timeseries_long_csv", "path": str(path)})
    if wide_rows:
        path = comparison_root / "timeseries_wide.csv"
        variant_columns = sorted(
            {key for row in wide_rows for key in row if key.startswith("value__")}
        )
        _write_csv(
            path,
            wide_rows,
            [
                "comparison_id",
                "observable",
                "variable",
                "support",
                "unit",
                "comparison_time_key",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
            ]
            + variant_columns,
        )
        artifacts.append({"kind": "timeseries_wide_csv", "path": str(path)})
    if delta_rows:
        path = comparison_root / "timeseries_delta.csv"
        _write_csv(
            path,
            delta_rows,
            [
                "comparison_id",
                "observable",
                "variable",
                "support",
                "variant_id",
                "reference_variant",
                "comparison_time_key",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
                "value",
                "reference_value",
                "signed_error",
                "absolute_error",
                "relative_error",
                "unit",
            ],
        )
        artifacts.append({"kind": "timeseries_delta_csv", "path": str(path)})
    return artifacts, long_rows, wide_rows, delta_rows


def _load_simulated_timeseries_csv(path: Path) -> tuple[list[dict[str, str]], str] | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    delimiter = ";" if ";" in raw.partition("\n")[0] else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = [{str(key): str(value) for key, value in row.items()} for row in reader]
    if not rows:
        return None
    return rows, delimiter


def write_native_timeseries_exports(
    *,
    comparison_id: str,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    reference_variant: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Write CSV exports from `_postprocess/_timeseries/_simulated_timeseries.csv` when present."""
    tables: dict[str, dict[str, Any]] = {}
    for summary in _completed_variant_summaries(variant_summaries):
        run_folder = Path(str(summary.get("run_folder", "")))
        source_path = run_folder / "_postprocess" / "_timeseries" / "_simulated_timeseries.csv"
        loaded = _load_simulated_timeseries_csv(source_path)
        if loaded is None:
            continue
        raw_rows, _ = loaded
        numeric_columns = {
            key
            for key in raw_rows[0].keys()
            if key != "date" and any(_as_float(row.get(key)) is not None for row in raw_rows)
        }
        tables[str(summary.get("id", ""))] = {
            "variant_id": str(summary.get("id", "")),
            "variant_label": str(summary.get("label", summary.get("id", ""))),
            "rows": raw_rows,
            "numeric_columns": numeric_columns,
            "source_path": str(source_path),
        }

    if len(tables) < 2:
        return [], [], [], []

    common_variables = sorted(
        set.intersection(*(table["numeric_columns"] for table in tables.values()))
    )
    if not common_variables:
        return [], [], [], []

    long_rows: list[dict[str, Any]] = []
    for table in tables.values():
        for time_index, raw_row in enumerate(table["rows"]):
            time_label = raw_row.get("date", str(time_index))
            for variable in common_variables:
                value = _as_float(raw_row.get(variable))
                if value is None:
                    continue
                long_rows.append(
                    {
                        "comparison_id": comparison_id,
                        "variant_id": table["variant_id"],
                        "variant_label": table["variant_label"],
                        "variable": variable,
                        "time_index": time_index,
                        "time_label": time_label,
                        "value": value,
                        "source_path": table["source_path"],
                    }
                )

    wide_index: dict[tuple[str, int], dict[str, Any]] = {}
    for row in long_rows:
        key = (str(row["variable"]), int(row["time_index"]))
        item = wide_index.setdefault(
            key,
            {
                "comparison_id": comparison_id,
                "variable": row["variable"],
                "time_index": row["time_index"],
                "time_label": row["time_label"],
            },
        )
        item[f"value__{row['variant_id']}"] = row["value"]
    wide_rows = list(wide_index.values())

    delta_rows: list[dict[str, Any]] = []
    if reference_variant is not None and reference_variant in tables:
        reference_index = {
            (str(row["variable"]), int(row["time_index"])): row
            for row in long_rows
            if str(row["variant_id"]) == reference_variant
        }
        for row in long_rows:
            if str(row["variant_id"]) == reference_variant:
                continue
            reference_row = reference_index.get((str(row["variable"]), int(row["time_index"])))
            if reference_row is None:
                continue
            signed_error = float(row["value"]) - float(reference_row["value"])
            absolute_error = abs(signed_error)
            ref_value = float(reference_row["value"])
            relative_error = absolute_error / abs(ref_value) if ref_value != 0.0 else math.nan
            delta_rows.append(
                {
                    "comparison_id": comparison_id,
                    "variant_id": row["variant_id"],
                    "reference_variant": reference_variant,
                    "variable": row["variable"],
                    "time_index": row["time_index"],
                    "time_label": row["time_label"],
                    "value": row["value"],
                    "reference_value": reference_row["value"],
                    "signed_error": signed_error,
                    "absolute_error": absolute_error,
                    "relative_error": relative_error,
                }
            )

    artifacts: list[dict[str, Any]] = []
    if long_rows:
        path = comparison_root / "native_timeseries_long.csv"
        _write_csv(
            path,
            long_rows,
            [
                "comparison_id",
                "variant_id",
                "variant_label",
                "variable",
                "time_index",
                "time_label",
                "value",
                "source_path",
            ],
        )
        artifacts.append({"kind": "native_timeseries_long_csv", "path": str(path)})
    if wide_rows:
        path = comparison_root / "native_timeseries_wide.csv"
        variant_columns = sorted(
            {key for row in wide_rows for key in row if key.startswith("value__")}
        )
        _write_csv(
            path,
            wide_rows,
            ["comparison_id", "variable", "time_index", "time_label"] + variant_columns,
        )
        artifacts.append({"kind": "native_timeseries_wide_csv", "path": str(path)})
    if delta_rows:
        path = comparison_root / "native_timeseries_delta.csv"
        _write_csv(
            path,
            delta_rows,
            [
                "comparison_id",
                "variant_id",
                "reference_variant",
                "variable",
                "time_index",
                "time_label",
                "value",
                "reference_value",
                "signed_error",
                "absolute_error",
                "relative_error",
            ],
        )
        artifacts.append({"kind": "native_timeseries_delta_csv", "path": str(path)})
    return artifacts, long_rows, wide_rows, delta_rows


def write_hydrographic_network_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    tolerance_m: float = 50.0,
    reference_role: str = "reference",
    candidate_role: str = "generated",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write one flat CSV of per-run hydrographic-network comparison metrics.

    The export is opportunistic: variants are skipped when their resolved run
    does not expose both canonical hydrographic-network features.
    """
    from hydromodpy.analysis.comparison.runtime import discover_result_store
    from hydromodpy.spatial.geographic.core.hydrographic_network import (
        canonical_feature_name_for_role,
    )

    reference_feature_name = canonical_feature_name_for_role(reference_role)
    candidate_feature_name = canonical_feature_name_for_role(candidate_role)
    if reference_feature_name is None or candidate_feature_name is None:
        raise ValueError(
            "Unknown hydrographic-network role. Expected canonical roles such as "
            "'reference' and 'generated'."
        )

    rows: list[dict[str, Any]] = []
    skipped_variants: list[dict[str, Any]] = []
    for summary in _completed_variant_summaries(variant_summaries):
        variant_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if preferred_sim_id in (None, "") else str(preferred_sim_id)
            ),
            preferred_name=(
                None if preferred_run_name in (None, "") else str(preferred_run_name)
            ),
        )
        if store is None or sim_id in (None, ""):
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "result_store_unavailable",
                    "available_roles": [],
                }
            )
            continue
        try:
            run = store[str(sim_id)]
            available_roles = run.available_hydrographic_network_roles()
            if not {reference_role, candidate_role}.issubset(set(available_roles)):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_required_roles",
                        "available_roles": available_roles,
                    }
                )
                continue
            row = run.hydrographic_network_comparison_metrics(
                reference_role=reference_role,
                candidate_role=candidate_role,
                tolerance_m=tolerance_m,
                comparison_id=comparison_id,
                variant_id=variant_id,
                variant_label=str(summary.get("label", summary.get("id", ""))),
                solver=str(summary.get("solver", "")),
                mesh_label=str(summary.get("mesh_label", "")),
                mesh_mode=str(summary.get("mesh_mode", "")),
                sim_id=str(sim_id),
                run_name=str(summary.get("run_name", "")),
                run_folder=str(summary.get("run_folder", "")),
                reference_feature_name=reference_feature_name,
                candidate_feature_name=candidate_feature_name,
            )
            rows.append(row)
        except Exception as exc:
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "comparison_metrics_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping hydrographic-network metrics export for variant '%s'.",
                variant_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = []
    if skipped_variants:
        skipped_path = comparison_root / "hydrographic_network_metrics_skipped.json"
        skipped_payload = {
            "comparison_id": comparison_id,
            "reference_role": reference_role,
            "candidate_role": candidate_role,
            "reference_feature_name": reference_feature_name,
            "candidate_feature_name": candidate_feature_name,
            "tolerance_m": float(tolerance_m),
            "skipped_variants": skipped_variants,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "hydrographic_network_metrics_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_variants)} variant(s) skipped for hydrographic-network "
                    "metrics export."
                ),
            }
        )
        logger.info(
            "Hydrographic-network metrics export skipped %d variant(s): %s",
            len(skipped_variants),
            ", ".join(str(item.get("variant_id", "")) for item in skipped_variants),
        )
    if not rows:
        return artifacts, rows

    path = comparison_root / "hydrographic_network_metrics.csv"
    _write_csv(path, rows, HYDROGRAPHIC_NETWORK_METRICS_FIELDS)
    artifacts.append({"kind": "hydrographic_network_metrics_csv", "path": str(path)})
    logger.info(
        "Wrote hydrographic-network metrics export for %d variant(s) to %s",
        len(rows),
        path,
    )
    return artifacts, rows


def write_simulated_active_network_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    persistence_threshold: float = 0.5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write scalar metrics for the simulated active drainage network.

    The export summarizes time-varying cell fields. It does not imply that a
    persisted ``hydrographic_network_simulated_active`` vector feature exists.
    """
    from hydromodpy.analysis.comparison.runtime import discover_result_store

    rows: list[dict[str, Any]] = []
    skipped_variants: list[dict[str, Any]] = []
    for summary in _completed_variant_summaries(variant_summaries):
        variant_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if preferred_sim_id in (None, "") else str(preferred_sim_id)
            ),
            preferred_name=(
                None if preferred_run_name in (None, "") else str(preferred_run_name)
            ),
        )
        if store is None or sim_id in (None, ""):
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "result_store_unavailable",
                    "source_variable": variable,
                }
            )
            continue
        try:
            run = store[str(sim_id)]
            metrics = run.simulated_active_network_metrics(
                variable=variable,
                threshold=threshold,
                persistence_threshold=persistence_threshold,
            )
            row = {
                "comparison_id": comparison_id,
                "variant_id": variant_id,
                "variant_label": str(summary.get("label", summary.get("id", ""))),
                "solver": str(summary.get("solver", "")),
                "mesh_label": str(summary.get("mesh_label", "")),
                "mesh_mode": str(summary.get("mesh_mode", "")),
                "sim_id": str(sim_id),
                "run_name": str(summary.get("run_name", "")),
                "run_folder": str(summary.get("run_folder", "")),
            }
            row.update(metrics)
            rows.append(row)
        except Exception as exc:
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "simulated_active_metrics_failed",
                    "source_variable": variable,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping simulated-active network metrics export for variant '%s'.",
                variant_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = []
    if skipped_variants:
        skipped_path = comparison_root / "simulated_active_network_metrics_skipped.json"
        skipped_payload = {
            "comparison_id": comparison_id,
            "source_variable": variable,
            "threshold": float(threshold),
            "persistence_threshold": float(persistence_threshold),
            "skipped_variants": skipped_variants,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "simulated_active_network_metrics_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_variants)} variant(s) skipped for simulated-active "
                    "network metrics export."
                ),
            }
        )
        logger.info(
            "Simulated-active network metrics export skipped %d variant(s): %s",
            len(skipped_variants),
            ", ".join(str(item.get("variant_id", "")) for item in skipped_variants),
        )
    if not rows:
        return artifacts, rows

    path = comparison_root / "simulated_active_network_metrics.csv"
    _write_csv(path, rows, SIMULATED_ACTIVE_NETWORK_METRICS_FIELDS)
    artifacts.append({"kind": "simulated_active_network_metrics_csv", "path": str(path)})
    logger.info(
        "Wrote simulated-active network metrics export for %d variant(s) to %s",
        len(rows),
        path,
    )
    return artifacts, rows


def write_simulated_active_network_overlap_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write cell-overlap metrics between simulated-active cells and a vector role.

    When ``mode`` is omitted, each run resolves its default from ``flow_regime``:
    steady runs use their steady-state field, transient runs use the persistent
    occupancy rule for backward compatibility.
    """
    from hydromodpy.analysis.comparison.runtime import discover_result_store

    rows: list[dict[str, Any]] = []
    skipped_variants: list[dict[str, Any]] = []
    for summary in _completed_variant_summaries(variant_summaries):
        variant_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if preferred_sim_id in (None, "") else str(preferred_sim_id)
            ),
            preferred_name=(
                None if preferred_run_name in (None, "") else str(preferred_run_name)
            ),
        )
        if store is None or sim_id in (None, ""):
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "result_store_unavailable",
                    "source_variable": variable,
                    "network_role": network_role,
                }
            )
            continue
        try:
            run = store[str(sim_id)]
            if not run.has_hydrographic_network(network_role):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_vector_network_role",
                        "network_role": network_role,
                        "available_roles": run.available_hydrographic_network_roles(),
                        "source_variable": variable,
                    }
                )
                continue
            if not run.has_field(variable):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_simulated_active_field",
                        "network_role": network_role,
                        "source_variable": variable,
                    }
                )
                continue
            zarr_root = store.open_zarr(str(sim_id)).root
            mesh = zarr_root.get("mesh")
            if (
                mesh is None
                or "vertices" not in mesh
                or "face_node_connectivity" not in mesh
            ):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_plottable_mesh",
                        "network_role": network_role,
                        "source_variable": variable,
                    }
                )
                continue
            metrics = run.simulated_active_network_overlap_metrics(
                network_role=network_role,
                variable=variable,
                threshold=threshold,
                mode=mode,
                persistence_threshold=persistence_threshold,
                timestep=timestep,
                buffer_m=buffer_m,
            )
            row = {
                "comparison_id": comparison_id,
                "variant_id": variant_id,
                "variant_label": str(summary.get("label", summary.get("id", ""))),
                "solver": str(summary.get("solver", "")),
                "mesh_label": str(summary.get("mesh_label", "")),
                "mesh_mode": str(summary.get("mesh_mode", "")),
                "sim_id": str(sim_id),
                "run_name": str(summary.get("run_name", "")),
                "run_folder": str(summary.get("run_folder", "")),
            }
            row.update(metrics)
            rows.append(row)
        except Exception as exc:
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "simulated_active_overlap_metrics_failed",
                    "source_variable": variable,
                    "network_role": network_role,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping simulated-active overlap metrics export for variant '%s'.",
                variant_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = []
    if skipped_variants:
        skipped_path = comparison_root / "simulated_active_network_overlap_metrics_skipped.json"
        skipped_payload = {
            "comparison_id": comparison_id,
            "network_role": network_role,
            "source_variable": variable,
            "threshold": float(threshold),
            "mode": mode or "auto",
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "buffer_m": float(buffer_m),
            "skipped_variants": skipped_variants,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "simulated_active_network_overlap_metrics_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_variants)} variant(s) skipped for simulated-active "
                    "network overlap metrics export."
                ),
            }
        )
        logger.info(
            "Simulated-active network overlap metrics export skipped %d variant(s): %s",
            len(skipped_variants),
            ", ".join(str(item.get("variant_id", "")) for item in skipped_variants),
        )
    if not rows:
        return artifacts, rows

    path = comparison_root / "simulated_active_network_overlap_metrics.csv"
    _write_csv(path, rows, SIMULATED_ACTIVE_NETWORK_OVERLAP_METRICS_FIELDS)
    artifacts.append(
        {"kind": "simulated_active_network_overlap_metrics_csv", "path": str(path)}
    )
    logger.info(
        "Wrote simulated-active network overlap metrics export for %d variant(s) to %s",
        len(rows),
        path,
    )
    return artifacts, rows


def write_simulated_active_network_distance_metrics_export(
    *,
    comparison_id: str,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    network_buffer_m: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write planar distance metrics between active cells and a vector role.

    The export complements overlap metrics. It is intentionally explicit about
    its ``distance_method`` because it is not the DEM-downslope criterion from
    Abherve et al.; it only uses currently persisted mesh, field and reference
    linework artifacts.
    """
    from hydromodpy.analysis.comparison.runtime import discover_result_store

    rows: list[dict[str, Any]] = []
    skipped_variants: list[dict[str, Any]] = []
    for summary in _completed_variant_summaries(variant_summaries):
        variant_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if preferred_sim_id in (None, "") else str(preferred_sim_id)
            ),
            preferred_name=(
                None if preferred_run_name in (None, "") else str(preferred_run_name)
            ),
        )
        if store is None or sim_id in (None, ""):
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "result_store_unavailable",
                    "source_variable": variable,
                    "network_role": network_role,
                }
            )
            continue
        try:
            run = store[str(sim_id)]
            if not run.has_hydrographic_network(network_role):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_vector_network_role",
                        "network_role": network_role,
                        "available_roles": run.available_hydrographic_network_roles(),
                        "source_variable": variable,
                    }
                )
                continue
            if not run.has_field(variable):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_simulated_active_field",
                        "network_role": network_role,
                        "source_variable": variable,
                    }
                )
                continue
            zarr_root = store.open_zarr(str(sim_id)).root
            mesh = zarr_root.get("mesh")
            if (
                mesh is None
                or "vertices" not in mesh
                or "face_node_connectivity" not in mesh
            ):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_plottable_mesh",
                        "network_role": network_role,
                        "source_variable": variable,
                    }
                )
                continue
            metrics = run.simulated_active_network_distance_metrics(
                network_role=network_role,
                variable=variable,
                threshold=threshold,
                mode=mode,
                persistence_threshold=persistence_threshold,
                timestep=timestep,
                network_buffer_m=network_buffer_m,
            )
            row = {
                "comparison_id": comparison_id,
                "variant_id": variant_id,
                "variant_label": str(summary.get("label", summary.get("id", ""))),
                "solver": str(summary.get("solver", "")),
                "mesh_label": str(summary.get("mesh_label", "")),
                "mesh_mode": str(summary.get("mesh_mode", "")),
                "sim_id": str(sim_id),
                "run_name": str(summary.get("run_name", "")),
                "run_folder": str(summary.get("run_folder", "")),
            }
            row.update(metrics)
            rows.append(row)
        except Exception as exc:
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "simulated_active_distance_metrics_failed",
                    "source_variable": variable,
                    "network_role": network_role,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping simulated-active distance metrics export for variant '%s'.",
                variant_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = []
    if skipped_variants:
        skipped_path = comparison_root / "simulated_active_network_distance_metrics_skipped.json"
        skipped_payload = {
            "comparison_id": comparison_id,
            "network_role": network_role,
            "source_variable": variable,
            "threshold": float(threshold),
            "mode": mode or "auto",
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "network_buffer_m": float(network_buffer_m),
            "skipped_variants": skipped_variants,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "simulated_active_network_distance_metrics_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_variants)} variant(s) skipped for simulated-active "
                    "network distance metrics export."
                ),
            }
        )
        logger.info(
            "Simulated-active network distance metrics export skipped %d variant(s): %s",
            len(skipped_variants),
            ", ".join(str(item.get("variant_id", "")) for item in skipped_variants),
        )
    if not rows:
        return artifacts, rows

    path = comparison_root / "simulated_active_network_distance_metrics.csv"
    _write_csv(path, rows, SIMULATED_ACTIVE_NETWORK_DISTANCE_METRICS_FIELDS)
    artifacts.append(
        {"kind": "simulated_active_network_distance_metrics_csv", "path": str(path)}
    )
    logger.info(
        "Wrote simulated-active network distance metrics export for %d variant(s) to %s",
        len(rows),
        path,
    )
    return artifacts, rows


def write_simulated_active_network_reference_figure_export(
    *,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    buffer_m: float = 0.0,
    dpi: int = 180,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Render per-variant simulated-active maps against the reference network.

    The comparison target is deliberately ``reference``. Missing reference
    linework skips the figure for that variant; it never falls back to the
    topography-derived ``generated`` network.
    """
    import matplotlib.pyplot as plt

    from hydromodpy.analysis.comparison.runtime import discover_result_store
    from hydromodpy.display import get as get_figure

    rows: list[dict[str, Any]] = []
    skipped_variants: list[dict[str, Any]] = []
    figure_root = comparison_root / "run_figures"
    figure_names = (
        "simulated_active_network",
        "simulated_active_network_reference_overlay",
    )

    for summary in _completed_variant_summaries(variant_summaries):
        variant_id = str(summary.get("id", ""))
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if preferred_sim_id in (None, "") else str(preferred_sim_id)
            ),
            preferred_name=(
                None if preferred_run_name in (None, "") else str(preferred_run_name)
            ),
        )
        if store is None or sim_id in (None, ""):
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "result_store_unavailable",
                    "source_variable": variable,
                    "network_role": network_role,
                }
            )
            continue

        try:
            run = store[str(sim_id)]
            if not run.has_field(variable):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_simulated_active_field",
                        "source_variable": variable,
                        "network_role": network_role,
                    }
                )
                continue
            if not run.has_hydrographic_network(network_role):
                skipped_variants.append(
                    {
                        "variant_id": variant_id,
                        "reason": "missing_vector_network_role",
                        "network_role": network_role,
                        "available_roles": run.available_hydrographic_network_roles(),
                        "source_variable": variable,
                    }
                )
                continue

            variant_dir = figure_root / variant_id
            for figure_name in figure_names:
                figure_path = variant_dir / f"{figure_name}.png"
                fig = get_figure(figure_name).plot(
                    run,
                    dpi=dpi,
                    save_path=figure_path,
                    variable=variable,
                    threshold=threshold,
                    mode=mode,
                    persistence_threshold=persistence_threshold,
                    timestep=timestep,
                    buffer_m=buffer_m,
                )
                plt.close(fig)
                row = {
                    "kind": "simulated_active_network_figure",
                    "variant_id": variant_id,
                    "figure_name": figure_name,
                    "path": str(figure_path),
                }
                rows.append(row)
        except Exception as exc:
            skipped_variants.append(
                {
                    "variant_id": variant_id,
                    "reason": "simulated_active_network_figure_failed",
                    "source_variable": variable,
                    "network_role": network_role,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            logger.debug(
                "Skipping simulated-active network figure export for variant '%s'.",
                variant_id,
                exc_info=True,
            )
        finally:
            try:
                store.close()
            except Exception:
                pass

    artifacts: list[dict[str, Any]] = list(rows)
    if skipped_variants:
        skipped_path = comparison_root / "simulated_active_network_figures_skipped.json"
        skipped_payload = {
            "network_role": network_role,
            "source_variable": variable,
            "threshold": float(threshold),
            "mode": mode or "auto",
            "persistence_threshold": float(persistence_threshold),
            "timestep": timestep,
            "buffer_m": float(buffer_m),
            "skipped_variants": skipped_variants,
        }
        skipped_path.parent.mkdir(parents=True, exist_ok=True)
        skipped_path.write_text(
            json.dumps(skipped_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append(
            {
                "kind": "simulated_active_network_figures_skipped_json",
                "path": str(skipped_path),
                "note": (
                    f"{len(skipped_variants)} variant(s) skipped for simulated-active "
                    "network figure export."
                ),
            }
        )

    return artifacts, rows


def _history_matrix(payload: Mapping[str, Any], key: str) -> np.ndarray | None:
    if key not in payload:
        return None
    values = np.asarray(payload[key], dtype=float)
    if values.ndim == 1:
        return values.reshape(1, -1)
    if values.ndim == 2:
        return values
    return None


def _elapsed_seconds_axis(period_lengths: np.ndarray, *, n_snapshots: int) -> np.ndarray:
    if n_snapshots <= 0:
        return np.asarray([], dtype=float)
    if period_lengths.size == n_snapshots - 1:
        elapsed = np.concatenate(
            (np.asarray([0.0], dtype=float), np.cumsum(period_lengths, dtype=float))
        )
        return np.asarray(elapsed, dtype=float)
    if period_lengths.size == n_snapshots:
        return np.asarray(np.cumsum(period_lengths, dtype=float), dtype=float)
    return np.arange(n_snapshots, dtype=float)


def _namespace_from_mapping(value: Any) -> Any:
    """Return an attribute-access view for one TOML/JSON mapping."""
    if isinstance(value, Mapping):
        return SimpleNamespace(
            **{str(key): _namespace_from_mapping(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return [_namespace_from_mapping(item) for item in value]
    return value


def _step_end_elapsed_seconds_from_config(
    config_path: Path | None,
    *,
    n_steps: int,
) -> np.ndarray:
    if config_path is None or n_steps <= 0:
        return np.arange(max(n_steps, 0), dtype=float)
    try:
        from hydromodpy.core.time import resolve_simulation_time_grid

        payload = load_toml_with_base_config(config_path)
        grid = resolve_simulation_time_grid(_namespace_from_mapping(payload))
    except Exception:
        return np.arange(n_steps, dtype=float)
    if grid is None:
        return np.arange(n_steps, dtype=float)
    axes = build_transient_time_axes(grid.period_lengths_seconds)
    if axes.n_steps == n_steps:
        return np.asarray(axes.step_end_elapsed_seconds, dtype=float)
    return np.arange(n_steps, dtype=float)


def _homogeneous_sy_from_config(config_path: Path | None) -> float | None:
    """Read a homogeneous `Sy` value from one generated simulation config."""
    if config_path is None:
        return None
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return None
    flow = payload.get("flow")
    if not isinstance(flow, Mapping):
        return None
    params = flow.get("param")
    if not isinstance(params, Mapping):
        return None
    sy_payload = params.get("Sy") or params.get("sy") or params.get("S") or params.get("s")
    if not isinstance(sy_payload, Mapping):
        return None

    candidates: list[Any] = []
    for section_name in ("field_homogeneous", "homogeneous"):
        section = sy_payload.get(section_name)
        if isinstance(section, Mapping) and "value" in section:
            candidates.append(section.get("value"))
    if "value" in sy_payload:
        candidates.append(sy_payload.get("value"))

    for candidate in candidates:
        try:
            scalar, _ = parse_scalar_and_unit(
                candidate,
                default_unit="-",
                location="flow.param.Sy",
            )
            value = float(scalar)
        except Exception:
            continue
        if math.isfinite(value):
            return value
    return None


def _flux_factor_to_m3_s(unit: str) -> float:
    """Return a factor to normalize a volumetric budget unit to m3/s."""
    text = str(unit or "m3/s").strip()
    if text == "":
        return 1.0
    try:
        return float(factor_to_m3_per_s(text))
    except Exception:
        return 1.0


def _catalog_budget_factor_to_m3_s(*, solver: str, unit: str) -> float:
    """Return the catalog budget conversion factor for one solver row.

    Older MODFLOW 6 catalog rows were labelled ``m3/d`` even though the
    HydroModPy MF6 wrapper runs TDIS in seconds and stores SI flux magnitudes.
    Treat those legacy labels as already-normalized for MF6 only.
    """
    unit_text = str(unit or "").strip().lower()
    solver_key = str(solver or "").strip().lower()
    if solver_key == "modflow6" and unit_text in {"m3/d", "m3/day", "m^3/day"}:
        return 1.0
    return _flux_factor_to_m3_s(unit)


def _storage_change_series_m3_s(
    *,
    head_history_m: np.ndarray | None,
    saturated_thickness_history_m: np.ndarray | None,
    area_m2: np.ndarray | None,
    storage_coefficient: np.ndarray | None,
    period_lengths_seconds: np.ndarray,
) -> np.ndarray | None:
    if (
        head_history_m is None
        or area_m2 is None
        or storage_coefficient is None
        or head_history_m.ndim != 2
    ):
        return None
    if not (head_history_m.shape[1] == area_m2.size == storage_coefficient.size):
        return None
    storage_state_m = head_history_m
    if (
        saturated_thickness_history_m is not None
        and saturated_thickness_history_m.ndim == 2
        and saturated_thickness_history_m.shape == head_history_m.shape
    ):
        storage_state_m = saturated_thickness_history_m

    n_snapshots = int(storage_state_m.shape[0])
    storage_change = np.full(n_snapshots, np.nan, dtype=float)
    if n_snapshots == 0:
        return storage_change

    if period_lengths_seconds.size == n_snapshots - 1:
        storage_change[0] = 0.0
        for index in range(1, n_snapshots):
            dt_seconds = float(period_lengths_seconds[index - 1])
            if dt_seconds <= 0.0 or not math.isfinite(dt_seconds):
                continue
            delta_storage_state_m = storage_state_m[index] - storage_state_m[index - 1]
            storage_change[index] = float(
                np.nansum(area_m2 * storage_coefficient * delta_storage_state_m) / dt_seconds
            )
        return storage_change

    if period_lengths_seconds.size == n_snapshots:
        storage_change[0] = 0.0
        for index in range(1, n_snapshots):
            dt_seconds = float(period_lengths_seconds[index])
            if dt_seconds <= 0.0 or not math.isfinite(dt_seconds):
                continue
            delta_storage_state_m = storage_state_m[index] - storage_state_m[index - 1]
            storage_change[index] = float(
                np.nansum(area_m2 * storage_coefficient * delta_storage_state_m) / dt_seconds
            )
        return storage_change

    return None


def _load_boussinesq_state_from_store(
    store: SimulationCatalog,
    sim_id: str,
) -> Mapping[str, Any] | None:
    """Try reading Boussinesq state arrays from the SimulationCatalog Zarr group.

    Returns a dict-like mapping of array names to numpy arrays (same
    interface as ``np.load(...)``), or ``None`` if unavailable.
    """
    try:
        grp = store.open_zarr_group(sim_id)
    except (KeyError, Exception):
        return None

    state_grp = grp.get("boussinesq_state")
    if state_grp is None:
        return None

    # Build a lazy dict reading arrays on demand.
    result: dict[str, np.ndarray] = {}
    try:
        for key in state_grp:
            result[key] = np.asarray(state_grp[key][:])
    except Exception:
        return None

    return result if result else None


def _load_boussinesq_budget_rows(
    summary: Mapping[str, Any],
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> list[dict[str, Any]]:
    run_folder = Path(str(summary.get("run_folder", "")))
    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))

    # --- Try SimulationCatalog first ------------------------------------------------
    payload: Mapping[str, Any] | None = None
    source_label: str = ""
    if store is not None and sim_id is not None:
        payload = _load_boussinesq_state_from_store(store, sim_id)
        if payload is not None:
            source_label = f"SimulationCatalog(sim_id={sim_id})"
            logger.debug(
                "Loaded Boussinesq state from SimulationCatalog for budget (sim_id=%s).",
                sim_id,
            )

    # --- Fallback to legacy .npz file -----------------------------------------
    if payload is None:
        npz_path = run_folder / "_boussinesq_state_history.npz"
        if not npz_path.exists():
            return []
        payload = np.load(npz_path, allow_pickle=True)
        source_label = str(npz_path)

    recharge_history = _history_matrix(payload, "recharge_rate_history_m_s")
    well_history = _history_matrix(payload, "well_flux_history_m3_s")
    drainage_history = _history_matrix(payload, "drainage_flux_history_m3_s")
    surface_history = _history_matrix(payload, "saturation_excess_history_m_s")
    dry_deficit_history = _history_matrix(payload, "dry_deficit_history_m_s")
    prescribed_head_history = _history_matrix(payload, "prescribed_head_flux_history_m3_s")
    head_history = _history_matrix(payload, "head_history_m")
    saturated_thickness_history = _history_matrix(payload, "saturated_thickness_history_m")

    n_snapshots = max(
        (
            int(matrix.shape[0])
            for matrix in (
                recharge_history,
                well_history,
                drainage_history,
                surface_history,
                dry_deficit_history,
                prescribed_head_history,
                head_history,
                saturated_thickness_history,
            )
            if matrix is not None
        ),
        default=0,
    )
    if n_snapshots <= 0:
        return []

    area_m2: np.ndarray | None = None
    storage_coefficient: np.ndarray | None = None
    n_cells = next(
        (
            int(matrix.shape[1])
            for matrix in (
                recharge_history,
                well_history,
                drainage_history,
                surface_history,
                dry_deficit_history,
                prescribed_head_history,
                head_history,
                saturated_thickness_history,
            )
            if matrix is not None and matrix.ndim == 2
        ),
        0,
    )
    if n_cells > 0:
        # Boussinesq has no structured-grid TOML section, so solver_name is
        # dropped: the function falls back to the exchange-bundle path.
        cells = resolve_bundle_cells(
            run_folder,
            config_path=config_path,
            expected_size=n_cells,
        )
        if cells is not None:
            if cells.area_m2 is not None:
                area_m2 = np.asarray(cells.area_m2, dtype=float).reshape(-1)
            if cells.storage_coefficient is not None:
                storage_coefficient = np.asarray(
                    cells.storage_coefficient,
                    dtype=float,
                ).reshape(-1)
            elif (sy_value := _homogeneous_sy_from_config(config_path)) is not None:
                storage_coefficient = np.full(n_cells, sy_value, dtype=float)

    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    elapsed_seconds = _elapsed_seconds_axis(
        period_lengths,
        n_snapshots=n_snapshots,
    )

    component_series: dict[str, np.ndarray] = {}
    if (
        recharge_history is not None
        and area_m2 is not None
        and recharge_history.shape[1] == area_m2.size
    ):
        component_series["recharge_total_m3_s"] = np.sum(
            recharge_history * area_m2[None, :],
            axis=1,
            dtype=float,
        )
    if well_history is not None:
        component_series["well_total_m3_s"] = np.sum(well_history, axis=1, dtype=float)
    if drainage_history is not None:
        component_series["drainage_total_m3_s"] = np.sum(
            drainage_history,
            axis=1,
            dtype=float,
        )
    if (
        surface_history is not None
        and area_m2 is not None
        and surface_history.shape[1] == area_m2.size
    ):
        component_series["surface_excess_total_m3_s"] = np.sum(
            np.maximum(surface_history, 0.0) * area_m2[None, :],
            axis=1,
            dtype=float,
        )
    if (
        dry_deficit_history is not None
        and area_m2 is not None
        and dry_deficit_history.shape[1] == area_m2.size
    ):
        component_series["dry_deficit_total_m3_s"] = np.sum(
            np.maximum(dry_deficit_history, 0.0) * area_m2[None, :],
            axis=1,
            dtype=float,
        )
    if prescribed_head_history is not None:
        component_series["prescribed_head_out_total_m3_s"] = np.sum(
            np.maximum(prescribed_head_history, 0.0),
            axis=1,
            dtype=float,
        )

    storage_change = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=saturated_thickness_history,
        area_m2=area_m2,
        storage_coefficient=storage_coefficient,
        period_lengths_seconds=period_lengths,
    )
    if storage_change is not None:
        component_series["storage_change_total_m3_s"] = storage_change

    if {
        "recharge_total_m3_s",
        "well_total_m3_s",
        "drainage_total_m3_s",
        "surface_excess_total_m3_s",
        "storage_change_total_m3_s",
    }.issubset(component_series):
        prescribed_out = component_series.get(
            "prescribed_head_out_total_m3_s",
            np.zeros_like(component_series["recharge_total_m3_s"], dtype=float),
        )
        component_series["closure_residual_m3_s"] = (
            component_series["recharge_total_m3_s"]
            + component_series["well_total_m3_s"]
            + component_series.get(
                "dry_deficit_total_m3_s",
                np.zeros_like(component_series["recharge_total_m3_s"], dtype=float),
            )
            - component_series["drainage_total_m3_s"]
            - component_series["surface_excess_total_m3_s"]
            - prescribed_out
            - component_series["storage_change_total_m3_s"]
        )

    time_labels = [
        (f"{elapsed / 86400.0:.1f} d" if math.isfinite(float(elapsed)) else str(index))
        for index, elapsed in enumerate(elapsed_seconds.tolist())
    ]
    rows: list[dict[str, Any]] = []
    for component, series in sorted(component_series.items()):
        values = np.asarray(series, dtype=float).reshape(-1)
        if values.size != n_snapshots:
            continue
        for time_index, value in enumerate(values.tolist()):
            if not math.isfinite(float(value)):
                continue
            rows.append(
                {
                    "variant_id": summary.get("id", ""),
                    "variant_label": summary.get("label", summary.get("id", "")),
                    "solver": summary.get("solver", ""),
                    "mesh_mode": summary.get("mesh_mode", ""),
                    "component": component,
                    "unit": "m3/s",
                    "time_index": time_index,
                    "elapsed_seconds": float(elapsed_seconds[time_index]),
                    "time_label": time_labels[time_index],
                    "value": float(value),
                    "source": source_label,
                }
            )
    return rows


def _mf_budget_component_name(component: str) -> str:
    key = str(component).strip().lower().replace("_", "-")
    aliases = {
        "rcha": "recharge_total_m3_s",
        "rch": "recharge_total_m3_s",
        "recharge": "recharge_total_m3_s",
        "drn": "drainage_total_m3_s",
        "drains": "drainage_total_m3_s",
        "drain": "drainage_total_m3_s",
        "chd": "prescribed_head_out_total_m3_s",
        "constant head": "prescribed_head_out_total_m3_s",
        "constant-head": "prescribed_head_out_total_m3_s",
        "evt": "evapotranspiration_total_m3_s",
        "et": "evapotranspiration_total_m3_s",
    }
    if key.startswith("sto"):
        return "storage_change_total_m3_s"
    if key.startswith("storage"):
        return "storage_change_total_m3_s"
    return aliases.get(key, "")


def _mf_budget_component_value_m3_s(component: str, flux_in: float, flux_out: float) -> float:
    target = _mf_budget_component_name(component)
    if target == "storage_change_total_m3_s":
        return float(flux_out) - float(flux_in)
    if target in {
        "drainage_total_m3_s",
        "prescribed_head_out_total_m3_s",
        "evapotranspiration_total_m3_s",
    }:
        return float(flux_out) - float(flux_in)
    return float(flux_in) - float(flux_out)


def _load_catalog_budget_rows(
    summary: Mapping[str, Any],
    store: SimulationCatalog | None,
    sim_id: str | None,
) -> list[dict[str, Any]]:
    """Load generic catalog budget rows and normalize them to comparison terms."""
    if store is None or sim_id in (None, ""):
        return []
    try:
        table = store.query_budget(str(sim_id))
    except Exception:
        return []
    if table is None or table.empty:
        return []

    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
    try:
        max_timestep = int(table["timestep"].max())
    except Exception:
        return []
    elapsed_axis = _step_end_elapsed_seconds_from_config(
        config_path,
        n_steps=max_timestep + 1,
    )

    component_values: dict[tuple[int, str], float] = {}
    for _, raw_row in table.iterrows():
        source_component = str(raw_row.get("component", ""))
        component = _mf_budget_component_name(source_component)
        if not component:
            continue
        try:
            timestep = int(raw_row.get("timestep"))
            factor = _catalog_budget_factor_to_m3_s(
                solver=str(summary.get("solver", "")),
                unit=str(raw_row.get("unit", "m3/s")),
            )
            flux_in = float(raw_row.get("flux_in", 0.0)) * factor
            flux_out = float(raw_row.get("flux_out", 0.0)) * factor
        except Exception:
            continue
        value = _mf_budget_component_value_m3_s(source_component, flux_in, flux_out)
        key = (timestep, component)
        component_values[key] = component_values.get(key, 0.0) + value

    if not component_values:
        return []

    grouped_by_time: dict[int, dict[str, float]] = {}
    for (timestep, component), value in component_values.items():
        grouped_by_time.setdefault(timestep, {})[component] = value
    for values in grouped_by_time.values():
        if {
            "recharge_total_m3_s",
            "storage_change_total_m3_s",
        }.issubset(values):
            values["closure_residual_m3_s"] = (
                values.get("recharge_total_m3_s", 0.0)
                - values.get("drainage_total_m3_s", 0.0)
                - values.get("surface_excess_total_m3_s", 0.0)
                - values.get("prescribed_head_out_total_m3_s", 0.0)
                - values.get("evapotranspiration_total_m3_s", 0.0)
                - values.get("storage_change_total_m3_s", 0.0)
            )

    rows: list[dict[str, Any]] = []
    for timestep, values in sorted(grouped_by_time.items()):
        elapsed = (
            float(elapsed_axis[timestep])
            if timestep < int(elapsed_axis.size)
            else float(timestep)
        )
        time_label = f"{elapsed / 86400.0:.1f} d" if math.isfinite(elapsed) else str(timestep)
        for component, value in sorted(values.items()):
            if not math.isfinite(float(value)):
                continue
            rows.append(
                {
                    "variant_id": summary.get("id", ""),
                    "variant_label": summary.get("label", summary.get("id", "")),
                    "solver": summary.get("solver", ""),
                    "mesh_mode": summary.get("mesh_mode", ""),
                    "component": component,
                    "unit": "m3/s",
                    "time_index": timestep,
                    "elapsed_seconds": elapsed,
                    "time_label": time_label,
                    "value": float(value),
                    "source": f"SimulationCatalog budgets(sim_id={sim_id})",
                }
            )
    return rows


BOUSSINESQ_OBSTACLE_DIAGNOSTICS_FIELDS = [
    "variant_id",
    "variant_label",
    "solver",
    "mesh_mode",
    "time_index",
    "elapsed_seconds",
    "time_label",
    "min_head_above_bottom_m",
    "max_head_below_bottom_m",
    "head_below_bottom_cell_count",
    "negative_storage_volume_m3",
    "max_head_above_surface_m",
    "head_above_surface_cell_count",
    "dry_deficit_active_cell_count",
    "dry_deficit_total_m3_s",
    "surface_excess_active_cell_count",
    "surface_excess_total_m3_s",
    "source",
]


def _load_boussinesq_obstacle_diagnostic_rows(
    summary: Mapping[str, Any],
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load lower/upper obstacle diagnostics from Boussinesq state histories."""
    run_folder = Path(str(summary.get("run_folder", "")))
    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))

    payload: Mapping[str, Any] | None = None
    source_label = ""
    if store is not None and sim_id is not None:
        payload = _load_boussinesq_state_from_store(store, sim_id)
        if payload is not None:
            source_label = f"SimulationCatalog(sim_id={sim_id})"

    if payload is None:
        npz_path = run_folder / "_boussinesq_state_history.npz"
        if not npz_path.exists():
            return []
        payload = np.load(npz_path, allow_pickle=True)
        source_label = str(npz_path)

    head_history = _history_matrix(payload, "head_history_m")
    if head_history is None or head_history.ndim != 2:
        return []

    n_snapshots, n_cells = int(head_history.shape[0]), int(head_history.shape[1])
    cells = resolve_bundle_cells(
        run_folder,
        config_path=config_path,
        expected_size=n_cells,
    )
    if cells is None:
        return []
    if (
        cells.z_top_m is None
        or cells.z_bottom_m is None
        or cells.z_top_m.size != n_cells
        or cells.z_bottom_m.size != n_cells
    ):
        return []

    area_m2 = (
        np.asarray(cells.area_m2, dtype=float).reshape(-1)
        if cells.area_m2 is not None and cells.area_m2.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )
    storage_coefficient = (
        np.asarray(cells.storage_coefficient, dtype=float).reshape(-1)
        if cells.storage_coefficient is not None and cells.storage_coefficient.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )
    z_top = (
        np.asarray(cells.z_top_m, dtype=float).reshape(-1)
        if cells.z_top_m is not None and cells.z_top_m.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )
    z_bottom = (
        np.asarray(cells.z_bottom_m, dtype=float).reshape(-1)
        if cells.z_bottom_m is not None and cells.z_bottom_m.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )

    dry_deficit_history = _history_matrix(payload, "dry_deficit_history_m_s")
    surface_history = _history_matrix(payload, "saturation_excess_history_m_s")
    if dry_deficit_history is None or dry_deficit_history.shape != head_history.shape:
        dry_deficit_history = np.zeros_like(head_history, dtype=float)
    if surface_history is None or surface_history.shape != head_history.shape:
        surface_history = np.zeros_like(head_history, dtype=float)

    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    elapsed_seconds = _elapsed_seconds_axis(period_lengths, n_snapshots=n_snapshots)
    time_labels = [
        (f"{elapsed / 86400.0:.1f} d" if math.isfinite(float(elapsed)) else str(index))
        for index, elapsed in enumerate(elapsed_seconds.tolist())
    ]

    rows: list[dict[str, Any]] = []
    for time_index in range(n_snapshots):
        head = np.asarray(head_history[time_index], dtype=float)
        bottom_gap = head - z_bottom
        top_gap = head - z_top
        bottom_violation = np.maximum(-bottom_gap, 0.0)
        top_violation = np.maximum(top_gap, 0.0)
        dry = np.maximum(np.asarray(dry_deficit_history[time_index], dtype=float), 0.0)
        surface = np.maximum(np.asarray(surface_history[time_index], dtype=float), 0.0)
        negative_storage_volume = area_m2 * storage_coefficient * bottom_violation
        rows.append(
            {
                "variant_id": summary.get("id", ""),
                "variant_label": summary.get("label", summary.get("id", "")),
                "solver": summary.get("solver", ""),
                "mesh_mode": summary.get("mesh_mode", ""),
                "time_index": time_index,
                "elapsed_seconds": float(elapsed_seconds[time_index]),
                "time_label": time_labels[time_index],
                "min_head_above_bottom_m": float(np.nanmin(bottom_gap)),
                "max_head_below_bottom_m": float(np.nanmax(bottom_violation)),
                "head_below_bottom_cell_count": int(np.nansum(bottom_violation > 0.0)),
                "negative_storage_volume_m3": float(np.nansum(negative_storage_volume)),
                "max_head_above_surface_m": float(np.nanmax(top_violation)),
                "head_above_surface_cell_count": int(np.nansum(top_violation > 0.0)),
                "dry_deficit_active_cell_count": int(np.nansum(dry > 1.0e-12)),
                "dry_deficit_total_m3_s": float(np.nansum(dry * area_m2)),
                "surface_excess_active_cell_count": int(np.nansum(surface > 1.0e-12)),
                "surface_excess_total_m3_s": float(np.nansum(surface * area_m2)),
                "source": source_label,
            }
        )
    return rows


def write_boussinesq_obstacle_diagnostics_export(
    *,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write per-snapshot Boussinesq obstacle diagnostics when available."""
    from hydromodpy.analysis.comparison.runtime import discover_result_store

    rows: list[dict[str, Any]] = []
    for summary in _completed_variant_summaries(variant_summaries):
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if preferred_sim_id in (None, "") else str(preferred_sim_id)
            ),
            preferred_name=(
                None if preferred_run_name in (None, "") else str(preferred_run_name)
            ),
        )
        try:
            rows.extend(
                _load_boussinesq_obstacle_diagnostic_rows(
                    summary,
                    store=store,
                    sim_id=sim_id,
                )
            )
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

    artifacts: list[dict[str, Any]] = []
    if not rows:
        return artifacts, rows

    path = comparison_root / "boussinesq_obstacle_diagnostics.csv"
    _write_csv(path, rows, BOUSSINESQ_OBSTACLE_DIAGNOSTICS_FIELDS)
    artifacts.append({"kind": "boussinesq_obstacle_diagnostics_csv", "path": str(path)})
    return artifacts, rows


def write_budget_exports(
    *,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write budget diagnostics derived from Boussinesq state histories."""
    from hydromodpy.analysis.comparison.runtime import discover_result_store

    rows: list[dict[str, Any]] = []
    for summary in _completed_variant_summaries(variant_summaries):
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(
                None if preferred_sim_id in (None, "") else str(preferred_sim_id)
            ),
            preferred_name=(
                None if preferred_run_name in (None, "") else str(preferred_run_name)
            ),
        )
        try:
            catalog_rows = _load_catalog_budget_rows(summary, store, sim_id)
            if catalog_rows:
                rows.extend(catalog_rows)
            rows.extend(_load_boussinesq_budget_rows(summary, store=store, sim_id=sim_id))
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

    artifacts: list[dict[str, Any]] = []
    if not rows:
        return artifacts, rows

    long_path = comparison_root / "budget_timeseries_long.csv"
    _write_csv(
        long_path,
        rows,
        [
            "variant_id",
            "variant_label",
            "solver",
            "mesh_mode",
            "component",
            "unit",
            "time_index",
            "elapsed_seconds",
            "time_label",
            "value",
            "source",
        ],
    )
    artifacts.append({"kind": "budget_timeseries_long_csv", "path": str(long_path)})

    wide_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        elapsed = _as_float(row.get("elapsed_seconds"))
        time_key = (
            f"elapsed_seconds:{elapsed:.9g}"
            if elapsed is not None
            else f"time_index:{int(row['time_index'])}"
        )
        key = (str(row["component"]), time_key)
        item = wide_index.setdefault(
            key,
            {
                "component": row["component"],
                "unit": row["unit"],
                "comparison_time_key": time_key,
                "time_index": row["time_index"],
                "elapsed_seconds": row["elapsed_seconds"],
                "time_label": row["time_label"],
            },
        )
        item[f"value__{row['variant_id']}"] = row["value"]
    wide_rows = list(wide_index.values())
    wide_path = comparison_root / "budget_timeseries_wide.csv"
    variant_columns = sorted({key for row in wide_rows for key in row if key.startswith("value__")})
    _write_csv(
        wide_path,
        wide_rows,
        ["component", "unit", "comparison_time_key", "time_index", "elapsed_seconds", "time_label"]
        + variant_columns,
    )
    artifacts.append({"kind": "budget_timeseries_wide_csv", "path": str(wide_path)})
    return artifacts, rows


def write_execution_summary_csv(
    *,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    reference_variant: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write one flat runtime summary CSV."""
    rows: list[dict[str, Any]] = []
    reference_runtime: float | None = None
    for summary in _completed_variant_summaries(variant_summaries):
        if str(summary.get("id", "")) == reference_variant:
            reference_runtime = _runtime_seconds(summary)
            break

    for summary in _completed_variant_summaries(variant_summaries):
        runtime_seconds = _runtime_seconds(summary)
        if runtime_seconds is None:
            continue
        speedup = (
            reference_runtime / runtime_seconds
            if reference_runtime is not None and runtime_seconds > 0.0
            else math.nan
        )
        rows.append(
            {
                "variant_id": summary.get("id", ""),
                "variant_label": summary.get("label", summary.get("id", "")),
                "solver": summary.get("solver", ""),
                "mesh_mode": summary.get("mesh_mode", ""),
                "runtime_seconds": runtime_seconds,
                "runtime_minutes": runtime_seconds / 60.0,
                "reference_variant": reference_variant or "",
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
                "variant_id",
                "variant_label",
                "solver",
                "mesh_mode",
                "runtime_seconds",
                "runtime_minutes",
                "reference_variant",
                "speedup_vs_reference",
            ],
        )
        artifacts.append({"kind": "execution_times_csv", "path": str(path)})
    return artifacts, rows


__all__ = (
    "write_boussinesq_obstacle_diagnostics_export",
    "write_budget_exports",
    "write_execution_summary_csv",
    "write_hydrographic_network_metrics_export",
    "write_native_timeseries_exports",
    "write_observable_chronicle_exports",
    "write_simulated_active_network_reference_figure_export",
    "write_simulated_active_network_metrics_export",
    "write_simulated_active_network_overlap_metrics_export",
)

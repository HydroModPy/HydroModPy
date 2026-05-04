"""Post-run equivalence audit for simulation-comparison experiments."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison import runtime_metadata
from hydromodpy.analysis.comparison.runtime_mesh import resolve_bundle_cells
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

_ORIGINAL_DISCOVER_RESULT_STORE = runtime_metadata.discover_result_store
discover_result_store = _ORIGINAL_DISCOVER_RESULT_STORE


def _discover_result_store(*args: Any, **kwargs: Any) -> Any:
    """Resolve stores while preserving old test monkeypatch entry points."""
    local_func = globals().get("discover_result_store", _ORIGINAL_DISCOVER_RESULT_STORE)
    module_func = runtime_metadata.discover_result_store
    if local_func is not _ORIGINAL_DISCOVER_RESULT_STORE and local_func is not module_func:
        return local_func(*args, **kwargs)
    return module_func(*args, **kwargs)


STRICT_METADATA_KEYS = (
    "mesh_hash",
    "mesh_topology",
    "n_cells",
    "n_layers",
    "n_timesteps",
    "crs_epsg",
    "bbox_xmin",
    "bbox_ymin",
    "bbox_xmax",
    "bbox_ymax",
    "period_start",
    "period_end",
    "time_unit",
    "geographic_fingerprint",
)

PHYSICAL_CONFIG_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("simulation.time", ("simulation", "time")),
    ("geographic", ("geographic",)),
    ("domain", ("domain",)),
    ("mesh_catchment", ("mesh_catchment",)),
    ("mesh_input", ("mesh_input",)),
    ("data.recharge", ("data", "recharge")),
    ("flow.flow_regime", ("flow", "flow_regime")),
    ("flow.active_sinks_sources", ("flow", "active_sinks_sources")),
    ("flow.active_bc", ("flow", "active_bc")),
    ("flow.param", ("flow", "param")),
    ("flow.ic", ("flow", "ic")),
    ("flow.bc", ("flow", "bc")),
    ("flow.sinks_sources.recharge", ("flow", "sinks_sources", "recharge")),
)

RECHARGE_COMPONENT = "recharge_total_m3_s"
RECHARGE_REL_TOL = 1.0e-2
RECHARGE_ABS_TOL_M3_S = 1.0e-6
HEAD_ABOVE_TOP_FRACTION_TOL = 5.0e-2
HEAD_ABOVE_TOP_TOL_M = 0.1
INITIAL_STATE_MISMATCH_SELECTORS = {"", "all", "first"}


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, bool)):
        return value
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    return str(value)


def _normalized_value(value: Any) -> str:
    item = _jsonable(value)
    return "" if item is None else str(item)


def _canonical_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_payload(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_canonical_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_payload(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return float(f"{value:.15g}")
    return _jsonable(value)


def _nested_value(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _section_fingerprint(value: Any) -> str:
    return json.dumps(_canonical_payload(value), sort_keys=True, separators=(",", ":"))


def _config_signature(config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        return {"status": "missing_config_path", "sections": {}, "fingerprints": {}}
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception as exc:
        return {
            "status": "load_error",
            "message": str(exc),
            "sections": {},
            "fingerprints": {},
        }

    sections: dict[str, Any] = {}
    fingerprints: dict[str, str] = {}
    for label, path in PHYSICAL_CONFIG_SECTIONS:
        value = _canonical_payload(_nested_value(payload, path))
        if value is None:
            continue
        sections[label] = value
        fingerprints[label] = _section_fingerprint(value)
    return {
        "status": "loaded",
        "config_path": str(config_path),
        "sections": sections,
        "fingerprints": fingerprints,
    }


def _simulation_row(store: Any, sim_id: str) -> dict[str, Any]:
    sims = store.list_simulations()
    if sims.empty or "sim_id" not in sims.columns:
        return {}
    matches = sims.loc[sims["sim_id"].astype(str) == str(sim_id)]
    if matches.empty:
        return {}
    return {key: _jsonable(value) for key, value in matches.iloc[-1].to_dict().items()}


def _parameter_signature(store: Any, sim_id: str) -> list[dict[str, Any]]:
    try:
        rows = store.connection.execute(
            """
            SELECT param_name, zone_id, value, unit, parameterization
              FROM parameters
             WHERE sim_id = ?
             ORDER BY param_name, zone_id
            """,
            [str(sim_id)],
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "param_name": str(row[0]),
            "zone_id": str(row[1]),
            "value": None if row[2] is None else float(row[2]),
            "unit": "" if row[3] is None else str(row[3]),
            "parameterization": "" if row[4] is None else str(row[4]),
        }
        for row in rows
    ]


def _budget_rows(summary: Mapping[str, Any], store: Any, sim_id: str) -> list[dict[str, Any]]:
    try:
        from hydromodpy.analysis.comparison.exports import (
            _load_boussinesq_budget_rows,
            _load_catalog_budget_rows,
        )

        rows = _load_catalog_budget_rows(summary, store, sim_id)
        rows.extend(_load_boussinesq_budget_rows(summary, store=store, sim_id=sim_id))
        return rows
    except Exception:
        return []


def _component_series(
    rows: Iterable[Mapping[str, Any]],
    component: str,
) -> dict[str, float]:
    series: dict[str, float] = {}
    for row in rows:
        if str(row.get("component", "")) != component:
            continue
        try:
            elapsed = float(row.get("elapsed_seconds"))
            value = float(row.get("value"))
        except Exception:
            continue
        if not (math.isfinite(elapsed) and math.isfinite(value)):
            continue
        series[f"elapsed_seconds:{elapsed:.9g}"] = value
    return series


def _series_summary(series: Mapping[str, float]) -> dict[str, Any]:
    values = [float(value) for value in series.values() if math.isfinite(float(value))]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def _compare_scalar_series(
    *,
    simulation_id: str,
    reference_simulation: str,
    component: str,
    values: Mapping[str, float],
    reference_values: Mapping[str, float],
) -> dict[str, Any]:
    common_keys = sorted(set(values).intersection(reference_values))
    differences: list[float] = []
    relative_differences: list[float] = []
    for key in common_keys:
        value = float(values[key])
        reference_value = float(reference_values[key])
        diff = value - reference_value
        differences.append(diff)
        scale = max(abs(value), abs(reference_value), 1.0e-30)
        relative_differences.append(abs(diff) / scale)

    if not differences:
        return {
            "simulation_id": simulation_id,
            "reference_simulation": reference_simulation,
            "component": component,
            "n_pairs": 0,
            "status": "missing_overlap",
        }

    abs_differences = [abs(value) for value in differences]
    max_abs_diff = max(abs_differences)
    mean_abs_diff = sum(abs_differences) / len(abs_differences)
    max_abs_rel_diff = max(relative_differences)
    status = (
        "pass"
        if max_abs_diff <= RECHARGE_ABS_TOL_M3_S or max_abs_rel_diff <= RECHARGE_REL_TOL
        else "warn"
    )
    return {
        "simulation_id": simulation_id,
        "reference_simulation": reference_simulation,
        "component": component,
        "n_pairs": len(differences),
        "status": status,
        "mean_abs_diff": mean_abs_diff,
        "max_abs_diff": max_abs_diff,
        "max_abs_rel_diff": max_abs_rel_diff,
        "tolerance_abs": RECHARGE_ABS_TOL_M3_S,
        "tolerance_rel": RECHARGE_REL_TOL,
    }


def _has_material_value(value: Any) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, Mapping):
        return any(_has_material_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_material_value(item) for item in value)
    return True


def _has_configured_recharge(subject: Mapping[str, Any]) -> bool:
    physical_config = subject.get("physical_config", {})
    sections = physical_config.get("sections", {}) if isinstance(physical_config, Mapping) else {}
    if not isinstance(sections, Mapping):
        return False

    active_sources = sections.get("flow.active_sinks_sources", [])
    if isinstance(active_sources, (list, tuple)) and any(
        str(item).strip().lower() == "recharge" for item in active_sources
    ):
        return True
    if str(active_sources).strip().lower() == "recharge":
        return True
    return _has_material_value(sections.get("data.recharge")) or _has_material_value(
        sections.get("flow.sinks_sources.recharge")
    )


def _recharge_series_for_audit(
    subject: Mapping[str, Any],
    *,
    fallback_keys: Iterable[str],
) -> dict[str, float]:
    budget_components = subject.get("budget_components", {})
    recharge = (
        budget_components.get(RECHARGE_COMPONENT, {}).get("series", {})
        if isinstance(budget_components, Mapping)
        else {}
    )
    if isinstance(recharge, Mapping) and recharge:
        return {str(key): float(value) for key, value in recharge.items()}
    if _has_configured_recharge(subject):
        return {}
    return {str(key): 0.0 for key in fallback_keys}


def _as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if math.isfinite(parsed) else None


def _row_cell_index(row: Mapping[str, Any]) -> int | None:
    for candidate in (row.get("selected_cell_index"), row.get("value_index")):
        if candidate in ("", None):
            continue
        try:
            return int(candidate)
        except Exception:
            continue
    return None


def _row_simulation_id(row: Mapping[str, Any]) -> str:
    """Return the comparison simulation id."""
    return str(row.get("simulation_id", ""))


def _head_bounds_diagnostics(
    *,
    observable_rows: Iterable[Mapping[str, Any]] | None,
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if observable_rows is None:
        return []

    cells_by_simulation = {}
    for summary in simulation_summaries:
        run_folder_raw = summary.get("run_folder")
        if run_folder_raw in ("", None):
            continue
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in ("", None) else Path(str(config_path_raw))
        cells = resolve_bundle_cells(
            Path(str(run_folder_raw)),
            config_path=config_path,
            solver_name=str(summary.get("solver", "")) or None,
        )
        if cells is not None:
            cells_by_simulation[str(summary.get("id", ""))] = cells

    grouped: dict[tuple[str, str], list[float]] = {}
    below_grouped: dict[tuple[str, str], list[float]] = {}
    counts: dict[tuple[str, str], int] = {}
    for row in observable_rows:
        variable = str(row.get("resolved_variable", row.get("variable", "")))
        if variable != "watertable_elevation":
            continue
        value = _as_float(row.get("value"))
        if value is None:
            continue
        simulation_id = _row_simulation_id(row)
        cell_index = _row_cell_index(row)
        cells = cells_by_simulation.get(simulation_id)
        if cell_index is None or cells is None:
            continue
        bounds = cells.vertical_bounds_for_cell_id(cell_index)
        if bounds is None:
            continue
        top, bottom = bounds
        key = (simulation_id, str(row.get("observable", "")))
        counts[key] = counts.get(key, 0) + 1
        above = value - top
        below = bottom - value
        if above > 0.0:
            grouped.setdefault(key, []).append(above)
        if below > 0.0:
            below_grouped.setdefault(key, []).append(below)

    diagnostics: list[dict[str, Any]] = []
    for key, n_values in sorted(counts.items()):
        simulation_id, observable = key
        above_values = grouped.get(key, [])
        below_values = below_grouped.get(key, [])
        diagnostics.append(
            {
                "simulation_id": simulation_id,
                "observable": observable,
                "n_values": n_values,
                "above_top_fraction": (len(above_values) / n_values if n_values else None),
                "above_top_mean_m": (
                    sum(above_values) / len(above_values) if above_values else 0.0
                ),
                "above_top_max_m": max(above_values) if above_values else 0.0,
                "below_bottom_fraction": (len(below_values) / n_values if n_values else None),
                "below_bottom_max_m": max(below_values) if below_values else 0.0,
            }
        )
    return diagnostics


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(right) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    cov = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True))
    left_var = sum((a - left_mean) ** 2 for a in left)
    right_var = sum((b - right_mean) ** 2 for b in right)
    denom = math.sqrt(left_var * right_var)
    if denom <= 0.0:
        return None
    return cov / denom


def _head_recharge_response_diagnostics(
    *,
    observable_rows: Iterable[Mapping[str, Any]] | None,
    recharge_by_simulation: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    if observable_rows is None:
        return []

    grouped: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in observable_rows:
        if str(row.get("support", "")) == "map":
            continue
        if str(row.get("is_initial_state", "")).strip().lower() == "true":
            continue
        variable = str(row.get("resolved_variable", row.get("variable", "")))
        if "head" not in variable and "watertable_elevation" not in variable:
            continue
        value = _as_float(row.get("value"))
        elapsed = _as_float(row.get("elapsed_seconds"))
        if value is None or elapsed is None:
            continue
        key = (
            _row_simulation_id(row),
            str(row.get("observable", "")),
            str(row.get("value_index", "")),
        )
        grouped.setdefault(key, {})[f"elapsed_seconds:{elapsed:.9g}"] = value

    diagnostics: list[dict[str, Any]] = []
    for (simulation_id, observable, value_index), head_series in sorted(grouped.items()):
        recharge_series = recharge_by_simulation.get(simulation_id, {})
        common_keys = sorted(set(head_series).intersection(recharge_series))
        if len(common_keys) < 3:
            continue
        heads = [float(head_series[key]) for key in common_keys]
        recharge = [float(recharge_series[key]) for key in common_keys]
        delta_heads = [heads[index] - heads[index - 1] for index in range(1, len(heads))]
        delta_recharge = [
            recharge[index] - recharge[index - 1] for index in range(1, len(recharge))
        ]
        same_sign_count = sum(
            1
            for dh, dr in zip(delta_heads, delta_recharge, strict=True)
            if abs(dr) > 0.0 and dh * dr > 0.0
        )
        nonzero_recharge_steps = sum(1 for dr in delta_recharge if abs(dr) > 0.0)
        diagnostics.append(
            {
                "simulation_id": simulation_id,
                "observable": observable,
                "value_index": value_index,
                "n_pairs": len(common_keys),
                "head_range_m": max(heads) - min(heads),
                "recharge_range_m3_s": max(recharge) - min(recharge),
                "corr_recharge_head": _correlation(recharge, heads),
                "corr_delta_recharge_delta_head": _correlation(
                    delta_recharge,
                    delta_heads,
                ),
                "same_sign_delta_fraction": (
                    same_sign_count / nonzero_recharge_steps if nonzero_recharge_steps else None
                ),
            }
        )
    return diagnostics


def _is_true_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _initial_state_policy_diagnostics(
    *,
    observable_rows: Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Summarize whether extracted observables include solver-specific t0 rows."""
    if observable_rows is None:
        return []

    grouped: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = {}
    for row in observable_rows:
        observable = str(row.get("observable", ""))
        if observable == "":
            continue
        simulation_id = _row_simulation_id(row)
        if simulation_id == "":
            continue
        key = (
            observable,
            str(row.get("support", "")),
            str(row.get("requested_time", "")),
            str(row.get("resolved_variable", row.get("variable", ""))),
        )
        simulation_stats = grouped.setdefault(key, {}).setdefault(
            simulation_id,
            {
                "n_rows": 0,
                "n_initial_rows": 0,
                "n_step_end_rows": 0,
                "first_elapsed_seconds": None,
                "first_non_initial_elapsed_seconds": None,
            },
        )
        simulation_stats["n_rows"] += 1
        elapsed = _as_float(row.get("elapsed_seconds"))
        if elapsed is not None and simulation_stats["first_elapsed_seconds"] is None:
            simulation_stats["first_elapsed_seconds"] = elapsed
        if _is_true_flag(row.get("is_initial_state")):
            simulation_stats["n_initial_rows"] += 1
        else:
            simulation_stats["n_step_end_rows"] += 1
            if (
                elapsed is not None
                and simulation_stats["first_non_initial_elapsed_seconds"] is None
            ):
                simulation_stats["first_non_initial_elapsed_seconds"] = elapsed

    diagnostics: list[dict[str, Any]] = []
    for (observable, support, requested_time, variable), by_simulation in sorted(grouped.items()):
        if len(by_simulation) < 2:
            continue
        simulations_with_initial = sorted(
            simulation_id
            for simulation_id, stats in by_simulation.items()
            if int(stats.get("n_initial_rows", 0)) > 0
        )
        simulations_without_initial = sorted(
            simulation_id
            for simulation_id, stats in by_simulation.items()
            if int(stats.get("n_initial_rows", 0)) == 0
        )
        if not simulations_with_initial or not simulations_without_initial:
            continue
        selector = str(requested_time).strip().lower()
        severity = "warning" if selector in INITIAL_STATE_MISMATCH_SELECTORS else "info"
        diagnostics.append(
            {
                "observable": observable,
                "support": support,
                "requested_time": requested_time,
                "resolved_variable": variable,
                "severity": severity,
                "simulations_with_initial_state": simulations_with_initial,
                "simulations_without_initial_state": simulations_without_initial,
                "simulation_stats": by_simulation,
                "message": (
                    "Some simulations expose an explicit initial-state row while others "
                    "start at the first computed step."
                ),
            }
        )
    return diagnostics


def _load_audit_subject(summary: Mapping[str, Any]) -> dict[str, Any]:
    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
    preferred_sim_id = summary.get("sim_id")
    preferred_name = summary.get("run_name")
    store, sim_id = _discover_result_store(
        config_path,
        preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
        preferred_name=None if preferred_name in (None, "") else str(preferred_name),
    )
    try:
        config_signature = _config_signature(config_path)
        if store is None or sim_id is None:
            return {
                "id": summary.get("id", ""),
                "status": "missing_store",
                "metadata": {},
                "parameters": [],
                "physical_config": config_signature,
                "budget_components": {},
            }
        budget_rows = _budget_rows(summary, store, str(sim_id))
        recharge_series = _component_series(budget_rows, RECHARGE_COMPONENT)
        return {
            "id": summary.get("id", ""),
            "status": "loaded",
            "sim_id": str(sim_id),
            "metadata": _simulation_row(store, str(sim_id)),
            "parameters": _parameter_signature(store, str(sim_id)),
            "physical_config": config_signature,
            "budget_components": {
                RECHARGE_COMPONENT: {
                    "summary": _series_summary(recharge_series),
                    "series": recharge_series,
                }
            },
        }
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


def build_equivalence_audit(
    *,
    simulation_summaries: Iterable[Mapping[str, Any]] | None = None,
    reference_simulation: str | None = None,
    mode: str = "strict_same_case",
    on_mismatch: str = "fail",
    observable_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a comparison audit without modifying child simulations."""
    if simulation_summaries is None:
        summaries = ()
    else:
        summaries = simulation_summaries
    reference_id = reference_simulation
    completed = [
        dict(summary)
        for summary in summaries
        if str(summary.get("status", "")) in {"completed", "reused"}
    ]
    subjects = [_load_audit_subject(summary) for summary in completed]
    subject_by_id = {str(subject.get("id", "")): subject for subject in subjects}
    reference_id = reference_id or (str(completed[0].get("id", "")) if completed else None)
    reference = subject_by_id.get(str(reference_id)) if reference_id else None

    issues: list[dict[str, Any]] = []
    if reference is None:
        issues.append(
            {
                "level": "error",
                "kind": "missing_reference",
                "message": "No completed reference simulation is available for audit.",
            }
        )
    else:
        ref_metadata = reference.get("metadata", {})
        ref_parameters = reference.get("parameters", [])
        ref_config = reference.get("physical_config", {})
        ref_fingerprints = ref_config.get("fingerprints", {})
        ref_budget_components = reference.get("budget_components", {})
        ref_recharge_raw = ref_budget_components.get(RECHARGE_COMPONENT, {}).get("series", {})
        for subject in subjects:
            simulation_id = str(subject.get("id", ""))
            if simulation_id == reference_id:
                continue
            metadata = subject.get("metadata", {})
            for key in STRICT_METADATA_KEYS:
                left = _normalized_value(metadata.get(key))
                right = _normalized_value(ref_metadata.get(key))
                if left == "" and right == "":
                    continue
                if left != right:
                    issues.append(
                        {
                            "level": "error" if on_mismatch == "fail" else "warning",
                            "kind": "metadata_mismatch",
                            "simulation_id": simulation_id,
                            "reference_simulation": reference_id,
                            "field": key,
                            "value": metadata.get(key),
                            "reference_value": ref_metadata.get(key),
                        }
                    )
            if subject.get("parameters", []) != ref_parameters:
                issues.append(
                    {
                        "level": "error" if on_mismatch == "fail" else "warning",
                        "kind": "parameter_mismatch",
                        "simulation_id": simulation_id,
                        "reference_simulation": reference_id,
                        "message": "Persisted parameter tables differ from the reference.",
                    }
                )
            config = subject.get("physical_config", {})
            fingerprints = config.get("fingerprints", {})
            for section_name, reference_fingerprint in ref_fingerprints.items():
                candidate_fingerprint = fingerprints.get(section_name, "")
                if candidate_fingerprint == reference_fingerprint:
                    continue
                issues.append(
                    {
                        "level": "error" if on_mismatch == "fail" else "warning",
                        "kind": "config_section_mismatch",
                        "simulation_id": simulation_id,
                        "reference_simulation": reference_id,
                        "field": section_name,
                        "message": "Physical-case TOML section differs from the reference.",
                    }
                )

            budget_components = subject.get("budget_components", {})
            recharge_raw = budget_components.get(RECHARGE_COMPONENT, {}).get("series", {})
            recharge_keys = sorted(set(ref_recharge_raw).union(set(recharge_raw)))
            ref_recharge = _recharge_series_for_audit(
                reference,
                fallback_keys=recharge_keys,
            )
            recharge = _recharge_series_for_audit(
                subject,
                fallback_keys=recharge_keys,
            )
            recharge_check = _compare_scalar_series(
                simulation_id=simulation_id,
                reference_simulation=str(reference_id),
                component=RECHARGE_COMPONENT,
                values=recharge,
                reference_values=ref_recharge,
            )
            subject.setdefault("budget_checks", {})[RECHARGE_COMPONENT] = recharge_check
            if recharge_check.get("status") != "pass":
                issues.append(
                    {
                        "level": "error" if on_mismatch == "fail" else "warning",
                        "kind": "recharge_budget_mismatch",
                        "simulation_id": simulation_id,
                        "reference_simulation": reference_id,
                        "field": RECHARGE_COMPONENT,
                        "message": "Persisted recharge totals differ from the reference.",
                        "max_abs_diff": recharge_check.get("max_abs_diff"),
                        "max_abs_rel_diff": recharge_check.get("max_abs_rel_diff"),
                        "n_pairs": recharge_check.get("n_pairs"),
                    }
                )

    head_bounds = _head_bounds_diagnostics(
        observable_rows=observable_rows,
        simulation_summaries=completed,
    )
    for item in head_bounds:
        above_fraction = _as_float(item.get("above_top_fraction")) or 0.0
        above_max = _as_float(item.get("above_top_max_m")) or 0.0
        if above_fraction > HEAD_ABOVE_TOP_FRACTION_TOL and above_max > HEAD_ABOVE_TOP_TOL_M:
            issues.append(
                {
                    "level": "error" if on_mismatch == "fail" else "warning",
                    "kind": "watertable_above_top",
                    "simulation_id": item.get("simulation_id", ""),
                    "field": item.get("observable", ""),
                    "message": (
                        "Watertable elevation is above the model top on a large fraction of cells."
                    ),
                    "above_top_fraction": above_fraction,
                    "above_top_max_m": above_max,
                    "fraction_tolerance": HEAD_ABOVE_TOP_FRACTION_TOL,
                    "height_tolerance_m": HEAD_ABOVE_TOP_TOL_M,
                }
            )

    initial_state_policy = _initial_state_policy_diagnostics(
        observable_rows=observable_rows,
    )
    for item in initial_state_policy:
        if str(item.get("severity", "")) != "warning":
            continue
        issues.append(
            {
                "level": "warning",
                "kind": "initial_state_policy_mismatch",
                "simulation_id": ",".join(item.get("simulations_with_initial_state", [])),
                "field": item.get("observable", ""),
                "message": item.get("message", ""),
                "requested_time": item.get("requested_time", ""),
                "simulations_with_initial_state": item.get("simulations_with_initial_state", []),
                "simulations_without_initial_state": item.get(
                    "simulations_without_initial_state", []
                ),
            }
        )

    has_error = any(issue.get("level") == "error" for issue in issues)
    has_warning = any(issue.get("level") == "warning" for issue in issues)
    status = "fail" if has_error else "warn" if has_warning else "pass"
    recharge_by_simulation = {
        str(subject.get("id", "")): subject.get("budget_components", {})
        .get(RECHARGE_COMPONENT, {})
        .get("series", {})
        for subject in subjects
    }
    return {
        "schema_version": "simulation_comparison_audit_v1",
        "mode": mode,
        "on_mismatch": on_mismatch,
        "status": status,
        "reference_simulation": reference_id,
        "physical_config_sections": [label for label, _ in PHYSICAL_CONFIG_SECTIONS],
        "initial_state_policy": initial_state_policy,
        "head_bounds": head_bounds,
        "head_recharge_response": _head_recharge_response_diagnostics(
            observable_rows=observable_rows,
            recharge_by_simulation=recharge_by_simulation,
        ),
        "subjects": subjects,
        "issues": issues,
    }


def write_audit_files(
    *,
    comparison_root: Path,
    audit: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Write machine-readable and Markdown audit summaries."""
    comparison_root.mkdir(parents=True, exist_ok=True)
    json_path = comparison_root / "comparison_audit.json"
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    lines = [
        f"# Comparison Audit: {audit.get('status', '')}",
        "",
        f"- Reference simulation: `{audit.get('reference_simulation', '')}`",
        f"- Mode: `{audit.get('mode', '')}`",
        f"- Issues: {len(audit.get('issues', []))}",
        f"- Physical config sections: {len(audit.get('physical_config_sections', []))}",
        "",
        "## Issues",
    ]
    issues = list(audit.get("issues", []))
    if not issues:
        lines.append("- No equivalence issue detected.")
    else:
        for issue in issues:
            field = issue.get("field")
            suffix = f" field=`{field}`" if field else ""
            simulation_id = issue.get("simulation_id", "")
            lines.append(
                f"- `{issue.get('level', '')}` / `{issue.get('kind', '')}`"
                f" simulation=`{simulation_id}`{suffix}"
            )
    config_issue_count = sum(
        1 for issue in issues if issue.get("kind") == "config_section_mismatch"
    )
    lines.extend(["", "## Physical Config Checks"])
    if config_issue_count:
        lines.append(f"- Physical config section mismatches: {config_issue_count}.")
    else:
        lines.append("- No physical config section mismatch detected.")

    lines.extend(["", "## Recharge Budget Checks"])
    subjects = list(audit.get("subjects", []))
    wrote_check = False
    for subject in subjects:
        checks = subject.get("budget_checks", {})
        check = checks.get(RECHARGE_COMPONENT)
        if not isinstance(check, Mapping):
            continue
        wrote_check = True
        lines.append(
            "- "
            f"`{subject.get('id', '')}` / `{RECHARGE_COMPONENT}`: "
            f"status=`{check.get('status', '')}`, "
            f"pairs={check.get('n_pairs', '')}, "
            f"max_abs_diff={check.get('max_abs_diff', '')}, "
            f"max_abs_rel_diff={check.get('max_abs_rel_diff', '')}"
        )
    if not wrote_check:
        lines.append("- No comparable recharge budget check was produced.")

    initial_policy = list(audit.get("initial_state_policy", []))
    lines.extend(["", "## Initial-State Policy"])
    if not initial_policy:
        lines.append("- No mixed initial-state policy was detected.")
    else:
        for item in initial_policy:
            with_initial = ", ".join(item.get("simulations_with_initial_state", []))
            without_initial = ", ".join(item.get("simulations_without_initial_state", []))
            lines.append(
                "- "
                f"`{item.get('observable', '')}` requested_time=`{item.get('requested_time', '')}`: "
                f"with_initial=`{with_initial}`, without_initial=`{without_initial}`, "
                f"severity=`{item.get('severity', '')}`"
            )

    head_bounds = list(audit.get("head_bounds", []))
    lines.extend(["", "## Head Bounds"])
    if not head_bounds:
        lines.append("- No head/top-bottom diagnostic was produced.")
    else:
        for item in head_bounds:
            simulation_id = item.get("simulation_id", "")
            lines.append(
                "- "
                f"`{simulation_id}` / `{item.get('observable', '')}`: "
                f"above_top_fraction={item.get('above_top_fraction', '')}, "
                f"above_top_max_m={item.get('above_top_max_m', '')}, "
                f"below_bottom_fraction={item.get('below_bottom_fraction', '')}"
            )

    diagnostics = list(audit.get("head_recharge_response", []))
    lines.extend(["", "## Head-Recharge Response"])
    if not diagnostics:
        lines.append("- No point-head diagnostic was produced.")
    else:
        for item in diagnostics:
            simulation_id = item.get("simulation_id", "")
            lines.append(
                "- "
                f"`{simulation_id}` / `{item.get('observable', '')}`: "
                f"head_range_m={item.get('head_range_m', '')}, "
                f"corr_delta_recharge_delta_head={item.get('corr_delta_recharge_delta_head', '')}, "
                f"same_sign_delta_fraction={item.get('same_sign_delta_fraction', '')}"
            )
    md_path = comparison_root / "comparison_audit.md"
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, md_path


__all__ = (
    "build_equivalence_audit",
    "write_audit_files",
)

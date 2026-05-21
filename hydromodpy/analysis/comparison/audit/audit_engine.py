"""Compute layer of the equivalence audit.

Pure functions that consume audit subjects (loaded by ``audit_io``) and
build the comparison report dictionary returned by
``build_equivalence_audit``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.runtime.mesh import resolve_bundle_cells

from .audit_io import (
    HEAD_ABOVE_TOP_FRACTION_TOL,
    HEAD_ABOVE_TOP_TOL_M,
    INITIAL_STATE_MISMATCH_SELECTORS,
    PHYSICAL_CONFIG_SECTIONS,
    RECHARGE_ABS_TOL_M3_S,
    RECHARGE_COMPONENT,
    RECHARGE_REL_TOL,
    STRICT_METADATA_KEYS,
    _load_audit_subject,
    _normalized_value,
    _section_fingerprint,
)


def _solver_name(subject: Mapping[str, Any]) -> str:
    direct = str(subject.get("solver", "") or "").strip().lower()
    if direct:
        return direct
    metadata = subject.get("metadata", {})
    if isinstance(metadata, Mapping):
        return str(metadata.get("solver", "") or "").strip().lower()
    return ""


def _flow_bc_without_method_specific_drainage_conductance(value: Any) -> tuple[Any, bool]:
    """Return a normalized flow.bc payload and whether drainage conductance was ignored."""

    ignored = False

    def normalize(item: Any) -> Any:
        nonlocal ignored
        if isinstance(item, Mapping):
            out: dict[str, Any] = {}
            for key, raw in item.items():
                key_text = str(key)
                if key_text == "description":
                    continue
                out[key_text] = normalize(raw)
            return out
        if isinstance(item, list):
            return [normalize(raw) for raw in item]
        if isinstance(item, tuple):
            return [normalize(raw) for raw in item]
        return item

    normalized = normalize(value)
    if not isinstance(normalized, dict):
        return normalized, ignored

    for family in ("cauchy", "robin"):
        family_payload = normalized.get(family)
        if not isinstance(family_payload, dict):
            continue
        drainage = family_payload.get("drainage")
        if not isinstance(drainage, dict):
            continue
        if "value" in drainage:
            drainage["value"] = "<method-specific-drainage-conductance>"
            ignored = True
    return normalized, ignored


def _is_expected_boussinesq_drainage_bc_difference(
    *,
    candidate_section: Any,
    reference_section: Any,
    subject: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> bool:
    """Return True for the deliberate MF6/Boussinesq drainage conductance delta."""

    candidate_solver = _solver_name(subject)
    reference_solver = _solver_name(reference)
    if candidate_solver != "boussinesq" or reference_solver not in {"modflow6", "mf6"}:
        return False

    candidate_normalized, candidate_ignored = _flow_bc_without_method_specific_drainage_conductance(
        candidate_section
    )
    reference_normalized, reference_ignored = _flow_bc_without_method_specific_drainage_conductance(
        reference_section
    )
    if not (candidate_ignored and reference_ignored):
        return False
    return _section_fingerprint(candidate_normalized) == _section_fingerprint(reference_normalized)


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
    solver_by_simulation: dict[str, str] = {}
    for summary in simulation_summaries:
        simulation_id = str(summary.get("id", ""))
        solver_name = str(summary.get("solver", "") or "")
        solver_by_simulation[simulation_id] = solver_name
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
            cells_by_simulation[simulation_id] = cells

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
                "solver": solver_by_simulation.get(simulation_id, ""),
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
    ignored_issues: list[dict[str, Any]] = []
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
            config_sections = config.get("sections", {})
            fingerprints = config.get("fingerprints", {})
            for section_name, reference_fingerprint in ref_fingerprints.items():
                candidate_fingerprint = fingerprints.get(section_name, "")
                if candidate_fingerprint == reference_fingerprint:
                    continue
                if (
                    section_name == "flow.bc"
                    and isinstance(config_sections, Mapping)
                    and isinstance(ref_config.get("sections", {}), Mapping)
                    and _is_expected_boussinesq_drainage_bc_difference(
                        candidate_section=config_sections.get(section_name),
                        reference_section=ref_config.get("sections", {}).get(section_name),
                        subject=subject,
                        reference=reference,
                    )
                ):
                    ignored_issues.append(
                        {
                            "level": "ignored",
                            "kind": "config_section_mismatch",
                            "simulation_id": simulation_id,
                            "reference_simulation": reference_id,
                            "field": section_name,
                            "message": (
                                "Ignored solver-method drainage conductance difference "
                                "between MODFLOW 6 and Boussinesq."
                            ),
                        }
                    )
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
            issue = {
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
            if _solver_name(item) in {"modflow6", "mf6"}:
                ignored_issues.append(
                    {
                        **issue,
                        "level": "ignored",
                        "message": (
                            "Ignored MODFLOW 6 watertable-above-top diagnostic; "
                            "unconfined heads can be above cell top."
                        ),
                    }
                )
                continue
            issues.append(issue)

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
        "ignored_issues": ignored_issues,
    }

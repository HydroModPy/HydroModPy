"""Reporting helpers for the reference 2D zone-conformal case."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.case_config import (
    _resolve_constraint_usage,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalGeometryPayload,
    ZoneConformalMeshingInputs,
    ZoneConformalSourcePayload,
)


def _build_summary(
    *,
    result,
    source_payload: ZoneConformalSourcePayload,
    clipped_gdf: gpd.GeoDataFrame,
    domain_payload: ZoneConformalGeometryPayload,
) -> dict[str, Any]:
    zone_feature_counts = (
        clipped_gdf["zone_key"].astype(str).value_counts().sort_index()
    )
    summary = dict(result.summary)
    summary.update(
        {
            "field_id": str(source_payload.field_id),
            "source_kind": str(source_payload.source_kind),
            "source_path": str(source_payload.source_path),
            "n_source_features_total": int(
                source_payload.n_source_features_before_domain_clip
            ),
            "n_source_features_clipped": int(len(clipped_gdf)),
            "zone_feature_counts": {
                str(key): int(value) for key, value in zone_feature_counts.items()
            },
        }
    )
    summary.update(
        {str(key): value for key, value in dict(domain_payload.summary).items()}
    )
    return summary


def _build_constraints_qa_contract(
    *,
    summary: Mapping[str, Any],
    constraints_mode: str,
    refine_interfaces: bool,
) -> dict[str, Any]:
    usage = _resolve_constraint_usage(constraints_mode)
    uses_geology_constraints = usage.uses_geology_constraints
    uses_river_constraints = usage.uses_river_constraints

    zone_count = int(len(tuple(summary.get("zone_keys", ()))))
    interface_group_count = int(summary.get("interface_group_count", 0))
    river_payload = (
        dict(summary.get("river_trace", {}))
        if isinstance(summary.get("river_trace"), Mapping)
        else {}
    )
    linear_constraints_payload = (
        dict(summary.get("linear_constraints", {}))
        if isinstance(summary.get("linear_constraints"), Mapping)
        else {}
    )
    watershed_payload = (
        dict(linear_constraints_payload.get("watershed::boundary", {}))
        if isinstance(linear_constraints_payload.get("watershed::boundary"), Mapping)
        else {}
    )
    river_trace_provided = bool(river_payload.get("provided", False))
    river_line_count = int(river_payload.get("line_count", 0))
    river_curve_count = int(river_payload.get("curve_count", 0))
    river_embed_success = int(river_payload.get("embedded_surface_curve_pairs", 0))
    river_embed_failures = int(river_payload.get("embed_failures", 0))
    river_refined = bool(river_payload.get("refined_with_interface_field", False))
    watershed_boundary_provided = bool(watershed_payload.get("provided", False))
    watershed_boundary_curve_count = int(watershed_payload.get("curve_count", 0))
    watershed_boundary_embed_success = int(
        watershed_payload.get("embedded_surface_curve_pairs", 0)
    )
    watershed_boundary_refined = bool(
        watershed_payload.get("refined_with_interface_field", False)
    )
    river_curve_group_present = any(
        str(group.get("name", "")) == "river::trace"
        for group in summary.get("curve_physical_groups", ())
        if isinstance(group, Mapping)
    )
    watershed_boundary_curve_group_present = any(
        str(group.get("name", "")) == "watershed::boundary"
        for group in summary.get("curve_physical_groups", ())
        if isinstance(group, Mapping)
    )

    embed_attempts = int(river_embed_success + river_embed_failures)
    embed_success_rate = (
        None
        if embed_attempts <= 0
        else round(float(river_embed_success) / float(embed_attempts), 12)
    )
    embed_pairs_per_curve = (
        None
        if river_curve_count <= 0
        else round(float(river_embed_success) / float(river_curve_count), 12)
    )

    thresholds = {
        "min_zone_count": 1 if uses_geology_constraints else 0,
        "min_interface_group_count": 1 if uses_geology_constraints else 0,
        "min_river_curve_count": 1 if uses_river_constraints else 0,
        "min_embedded_surface_curve_pairs": 1 if uses_river_constraints else 0,
        "require_refinement_when_refine_interfaces_true": bool(
            uses_river_constraints and refine_interfaces
        ),
    }
    if watershed_boundary_provided:
        thresholds["min_watershed_boundary_curve_count"] = 1
    metrics = {
        "zone_count": zone_count,
        "interface_group_count": interface_group_count,
        "river_trace_provided": river_trace_provided,
        "river_line_count": river_line_count,
        "river_curve_count": river_curve_count,
        "river_curve_group_present": river_curve_group_present,
        "river_embed_success_pairs": river_embed_success,
        "river_embed_failures": river_embed_failures,
        "river_embed_attempts": embed_attempts,
        "river_embed_success_rate": embed_success_rate,
        "river_embed_pairs_per_curve": embed_pairs_per_curve,
        "river_refined_with_interface_field": river_refined,
        "refine_interfaces_config": bool(refine_interfaces),
    }
    if watershed_boundary_provided:
        metrics.update(
            {
                "watershed_boundary_provided": watershed_boundary_provided,
                "watershed_boundary_curve_count": watershed_boundary_curve_count,
                "watershed_boundary_curve_group_present": watershed_boundary_curve_group_present,
                "watershed_boundary_embedded_surface_curve_pairs": watershed_boundary_embed_success,
                "watershed_boundary_refined_with_interface_field": watershed_boundary_refined,
            }
        )
    checks: dict[str, bool] = {}
    if uses_geology_constraints:
        checks["has_zone_partition"] = bool(zone_count >= int(thresholds["min_zone_count"]))
        checks["has_geology_interfaces"] = bool(
            interface_group_count >= int(thresholds["min_interface_group_count"])
        )
    if uses_river_constraints:
        checks["river_trace_provided"] = bool(river_trace_provided)
        checks["river_curves_generated"] = bool(
            river_curve_count >= int(thresholds["min_river_curve_count"])
            and river_line_count > 0
        )
        checks["river_curve_group_present"] = bool(river_curve_group_present)
        checks["river_embedded_on_surfaces"] = bool(
            river_embed_success >= int(thresholds["min_embedded_surface_curve_pairs"])
        )
        checks["river_refinement_consistent_with_config"] = bool(
            (not bool(thresholds["require_refinement_when_refine_interfaces_true"]))
            or river_refined
        )
    if watershed_boundary_provided:
        checks["watershed_boundary_curves_generated"] = bool(
            watershed_boundary_curve_count
            >= int(thresholds["min_watershed_boundary_curve_count"])
        )
        checks["watershed_boundary_curve_group_present"] = bool(
            watershed_boundary_curve_group_present
        )
        checks["watershed_boundary_embedded_on_surfaces"] = bool(
            watershed_boundary_embed_success > 0
        )
    if constraints_mode == "geology_rivers":
        checks["geology_and_river_constraints_coexist"] = bool(
            checks.get("has_geology_interfaces", False)
            and checks.get("river_curves_generated", False)
        )

    return {
        "contract_version": "constraints_qa_v1",
        "mode": str(constraints_mode),
        "thresholds": thresholds,
        "metrics": metrics,
        "checks": checks,
        "overall_pass": bool(all(checks.values())),
    }


def _build_rivers_config_summary(rivers_cfg: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": str(rivers_cfg["source"]),
        "path": rivers_cfg["path"],
        "clip_to_domain": bool(rivers_cfg["clip_to_domain"]),
        "min_segment_length": float(rivers_cfg["min_segment_length"]),
        "snap_tolerance": float(rivers_cfg["snap_tolerance"]),
    }


def _build_watershed_boundary_config_summary(
    watershed_boundary_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "enabled": bool(watershed_boundary_cfg["enabled"]),
        "source": str(watershed_boundary_cfg["source"]),
        "clip_to_domain": bool(watershed_boundary_cfg["clip_to_domain"]),
        "min_segment_length": float(watershed_boundary_cfg["min_segment_length"]),
        "participates_in_refinement": bool(
            watershed_boundary_cfg["participates_in_refinement"]
        ),
        "smoothing": {
            "enabled": bool(watershed_boundary_cfg["smoothing"]["enabled"]),
            "simplify_tolerance": float(
                watershed_boundary_cfg["smoothing"]["simplify_tolerance"]
            ),
            "heal_tolerance": float(
                watershed_boundary_cfg["smoothing"]["heal_tolerance"]
            ),
            "min_polygon_area": float(
                watershed_boundary_cfg["smoothing"]["min_polygon_area"]
            ),
        },
    }


def _finalize_summary_payload(
    *,
    base_summary: Mapping[str, Any],
    meshing_inputs: ZoneConformalMeshingInputs,
    constraints_mode: str,
    refine_interfaces: bool,
    mesh_path: Path,
) -> dict[str, Any]:
    summary = dict(base_summary)
    summary["constraints_mode"] = str(constraints_mode)
    summary["interface_scope"] = dict(meshing_inputs.interface_scope_payload.summary)
    summary["refinement_scope"] = dict(meshing_inputs.refinement_scope_payload.summary)
    summary["constraints_qa"] = _build_constraints_qa_contract(
        summary=summary,
        constraints_mode=constraints_mode,
        refine_interfaces=bool(refine_interfaces),
    )
    qa_checks = (
        dict(summary.get("qa_checks", {}))
        if isinstance(summary.get("qa_checks"), Mapping)
        else {}
    )
    qa_checks["constraints_contract_pass"] = bool(
        summary["constraints_qa"]["overall_pass"]
    )
    summary["qa_checks"] = qa_checks

    if meshing_inputs.usage.uses_river_constraints and meshing_inputs.rivers_cfg is not None:
        summary["rivers_config"] = _build_rivers_config_summary(meshing_inputs.rivers_cfg)

    if meshing_inputs.watershed_boundary_cfg is not None:
        summary["watershed_boundary_config"] = _build_watershed_boundary_config_summary(
            meshing_inputs.watershed_boundary_cfg
        )
        linear_constraints_summary = summary.get("linear_constraints", {})
        if isinstance(linear_constraints_summary, Mapping):
            summary["watershed_boundary"] = dict(
                linear_constraints_summary.get("watershed::boundary", {})
            )

    summary["output_mesh"] = str(mesh_path)
    return summary


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


__all__ = [
    "_build_constraints_qa_contract",
    "_finalize_summary_payload",
    "_build_summary",
    "_write_json",
]

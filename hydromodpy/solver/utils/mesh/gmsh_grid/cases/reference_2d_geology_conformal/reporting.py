"""Reporting helpers for the reference 2D zone-conformal case."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd

from hydromodpy.solver.utils.mesh.gmsh_grid.cases.reference_2d_geology_conformal.contracts import (
    ZoneConformalConstraintFamilies,
    ZoneConformalGeometryPayload,
    ZoneConformalMeshingInputs,
    ZoneConformalRiversConfig,
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
    constraint_families: ZoneConformalConstraintFamilies,
    refine_interfaces: bool,
) -> dict[str, Any]:
    uses_geology_constraints = bool(constraint_families.geology_interface)
    uses_river_constraints = bool(constraint_families.river)

    zone_count = int(len(tuple(summary.get("zone_keys", ()))))
    interface_group_count = int(summary.get("interface_group_count", 0))
    river_payload = (
        dict(summary.get("river_trace", {}))
        if isinstance(summary.get("river_trace"), Mapping)
        else {}
    )
    river_trace_provided = bool(river_payload.get("provided", False))
    river_line_count = int(river_payload.get("line_count", 0))
    river_curve_count = int(river_payload.get("curve_count", 0))
    river_embed_success = int(river_payload.get("embedded_surface_curve_pairs", 0))
    river_embed_failures = int(river_payload.get("embed_failures", 0))
    river_refined = bool(river_payload.get("refined_with_interface_field", False))
    river_curve_group_present = any(
        str(group.get("name", "")) == "river::trace"
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
    if constraint_families.geology_interface and constraint_families.river:
        checks["geology_and_river_constraints_coexist"] = bool(
            checks.get("has_geology_interfaces", False)
            and checks.get("river_curves_generated", False)
        )

    return {
        "contract_version": "constraints_qa_v1",
        "mode": str(summary.get("constraints_mode", "")),
        "thresholds": thresholds,
        "metrics": metrics,
        "checks": checks,
        "overall_pass": bool(all(checks.values())),
    }


def _build_rivers_config_summary(
    rivers_cfg: ZoneConformalRiversConfig,
) -> dict[str, Any]:
    return {
        "source": rivers_cfg.source,
        "path": rivers_cfg.path,
        "clip_to_domain": rivers_cfg.clip_to_domain,
        "min_segment_length": rivers_cfg.min_segment_length,
        "snap_tolerance": rivers_cfg.snap_tolerance,
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
    summary["effective_domain"] = dict(meshing_inputs.effective_domain_payload.summary)

    if meshing_inputs.constraint_families.river and meshing_inputs.diagnostics.rivers_cfg is not None:
        summary["rivers_config"] = _build_rivers_config_summary(
            meshing_inputs.diagnostics.rivers_cfg
        )

    if meshing_inputs.zone_meshing_cfg.refinement_policy is not None:
        summary["refinement_policy_config"] = (
            meshing_inputs.zone_meshing_cfg.refinement_policy.to_mapping()
        )

    summary["constraints_qa"] = _build_constraints_qa_contract(
        summary=summary,
        constraint_families=meshing_inputs.constraint_families,
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

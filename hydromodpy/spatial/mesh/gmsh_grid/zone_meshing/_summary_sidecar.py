"""Stable public summary assembly for zone-conformal meshing.

The mesher emits a compact sidecar payload used by launchers, tests and QA
tools.  Keeping the summary logic outside ``conformal.py`` helps separate the
runtime meshing algorithm from its reporting layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ZoneCleaningSummary:
    """Compact cleanup summary copied to the public sidecar payload."""

    mode: str
    source_feature_count: int
    features_after_domain_clip_count: int
    invalid_geometries_repaired_count: int
    polygons_removed_by_area_threshold_count: int
    simplify_tolerance: float | None
    heal_tolerance: float | None
    min_polygon_area: float | None
    overlap_tolerance: float | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode),
            "source_feature_count": int(self.source_feature_count),
            "features_after_domain_clip_count": int(self.features_after_domain_clip_count),
            "invalid_geometries_repaired_count": int(self.invalid_geometries_repaired_count),
            "polygons_removed_by_area_threshold_count": int(
                self.polygons_removed_by_area_threshold_count
            ),
            "simplify_tolerance": (
                None if self.simplify_tolerance is None else float(self.simplify_tolerance)
            ),
            "heal_tolerance": (None if self.heal_tolerance is None else float(self.heal_tolerance)),
            "min_polygon_area": (
                None if self.min_polygon_area is None else float(self.min_polygon_area)
            ),
            "overlap_tolerance": (
                None if self.overlap_tolerance is None else float(self.overlap_tolerance)
            ),
        }


@dataclass(frozen=True)
class ZonePhysicalGroupsSummary:
    """Counts of physical groups emitted by the conformal mesher."""

    surface_group_count: int
    curve_group_count: int
    interface_group_count: int
    boundary_group_count: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "surface_group_count": int(self.surface_group_count),
            "curve_group_count": int(self.curve_group_count),
            "interface_group_count": int(self.interface_group_count),
            "boundary_group_count": int(self.boundary_group_count),
        }


@dataclass(frozen=True)
class ZoneLinearConstraintSummary:
    """Public summary fragment for one embedded linear constraint."""

    provided: bool
    kind: str
    line_count: int
    curve_count: int
    embedded_surface_curve_pairs: int
    embed_failures: int
    refined_with_interface_field: bool
    participates_in_refinement: bool

    def to_mapping(self) -> dict[str, Any]:
        return {
            "provided": bool(self.provided),
            "kind": str(self.kind),
            "line_count": int(self.line_count),
            "curve_count": int(self.curve_count),
            "embedded_surface_curve_pairs": int(self.embedded_surface_curve_pairs),
            "embed_failures": int(self.embed_failures),
            "refined_with_interface_field": bool(self.refined_with_interface_field),
            "participates_in_refinement": bool(self.participates_in_refinement),
        }


@dataclass(frozen=True)
class ZoneRiverTraceSummary:
    """Reduced public summary focused on the optional river trace."""

    provided: bool
    line_count: int
    curve_count: int
    embedded_surface_curve_pairs: int
    embed_failures: int
    refined_with_interface_field: bool

    @classmethod
    def from_constraint_summary(
        cls,
        summary: ZoneLinearConstraintSummary | None,
        *,
        provided: bool,
    ) -> ZoneRiverTraceSummary:
        if summary is None:
            return cls(
                provided=provided,
                line_count=0,
                curve_count=0,
                embedded_surface_curve_pairs=0,
                embed_failures=0,
                refined_with_interface_field=False,
            )
        return cls(
            provided=bool(summary.provided),
            line_count=int(summary.line_count),
            curve_count=int(summary.curve_count),
            embedded_surface_curve_pairs=int(summary.embedded_surface_curve_pairs),
            embed_failures=int(summary.embed_failures),
            refined_with_interface_field=bool(summary.refined_with_interface_field),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "provided": bool(self.provided),
            "line_count": int(self.line_count),
            "curve_count": int(self.curve_count),
            "embedded_surface_curve_pairs": int(self.embedded_surface_curve_pairs),
            "embed_failures": int(self.embed_failures),
            "refined_with_interface_field": bool(self.refined_with_interface_field),
        }


@dataclass(frozen=True)
class ZoneConformalQaChecks:
    """Simple QA checks emitted in the conformal summary sidecar."""

    coverage_gap: float
    coverage_tolerance: float
    coverage_within_tolerance: bool
    has_interface_groups: bool
    has_zone_surface_groups: bool

    def to_mapping(self) -> dict[str, Any]:
        return {
            "coverage_gap": round(float(self.coverage_gap), 12),
            "coverage_tolerance": round(float(self.coverage_tolerance), 12),
            "coverage_within_tolerance": bool(self.coverage_within_tolerance),
            "has_interface_groups": bool(self.has_interface_groups),
            "has_zone_surface_groups": bool(self.has_zone_surface_groups),
        }


def build_zone_conformal_summary(
    *,
    output_path_obj: Path,
    mesh: Any,
    partition: Any,
    physical_groups: Sequence[Any],
    curve_tags_by_name: Mapping[str, Sequence[int]],
    normalized_constraints: Sequence[Any],
    constraint_embed_success_by_name: Mapping[str, int],
    constraint_embed_failures_by_name: Mapping[str, int],
    river_trace: object | None,
    refine_interfaces_value: bool,
    refined_curve_tags: set[int],
    mesh_size_fields_summary: Mapping[str, Any],
    regional_background_summary: Mapping[str, Any] | None,
    global_size_value: float,
    min_size: float | None,
    max_size: float | None,
    effective_max_size: float,
    algorithm: str,
    refinement_policy_summary: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the stable public summary payload returned by the mesher."""
    physical_group_summaries = [group.to_summary() for group in physical_groups]
    surface_group_summaries = [
        group_summary
        for group_summary in physical_group_summaries
        if int(group_summary["dimension"]) == 2
    ]
    curve_group_summaries = [
        group_summary
        for group_summary in physical_group_summaries
        if int(group_summary["dimension"]) == 1
    ]
    cleaning_diagnostics_raw = (
        {}
        if partition.cleaning_diagnostics is None
        else {str(key): value for key, value in partition.cleaning_diagnostics.items()}
    )
    tolerances = (
        dict(cleaning_diagnostics_raw.get("tolerances", {})) if cleaning_diagnostics_raw else {}
    )
    domain_area_value = float(partition.domain_area)
    covered_area_value = float(partition.covered_area)
    coverage_gap = abs(domain_area_value - covered_area_value)
    overlap_tolerance = (
        float(tolerances.get("overlap_tolerance", 0.0))
        if "overlap_tolerance" in tolerances
        else 0.0
    )
    coverage_tolerance = max(overlap_tolerance, 1.0e-9)
    interface_group_count = int(
        sum(1 for name in curve_tags_by_name if name.startswith("interface::"))
    )
    boundary_group_count = int(
        sum(1 for name in curve_tags_by_name if name.startswith("boundary::"))
    )

    cleaning_summary = ZoneCleaningSummary(
        mode=str(cleaning_diagnostics_raw.get("cleaning_mode", "unknown")),
        source_feature_count=int(cleaning_diagnostics_raw.get("source_feature_count", 0)),
        features_after_domain_clip_count=int(
            cleaning_diagnostics_raw.get("features_after_domain_clip_count", 0)
        ),
        invalid_geometries_repaired_count=int(
            cleaning_diagnostics_raw.get("invalid_geometries_repaired_count", 0)
        ),
        polygons_removed_by_area_threshold_count=int(
            cleaning_diagnostics_raw.get("polygons_removed_by_area_threshold_count", 0)
        ),
        simplify_tolerance=(
            None
            if "simplify_tolerance" not in tolerances
            else float(tolerances.get("simplify_tolerance", 0.0))
        ),
        heal_tolerance=(
            None
            if "heal_tolerance" not in tolerances
            else float(tolerances.get("heal_tolerance", 0.0))
        ),
        min_polygon_area=(
            None
            if "min_polygon_area" not in tolerances
            else float(tolerances.get("min_polygon_area", 0.0))
        ),
        overlap_tolerance=(
            None
            if "overlap_tolerance" not in tolerances
            else float(tolerances.get("overlap_tolerance", 0.0))
        ),
    )
    physical_groups_summary = ZonePhysicalGroupsSummary(
        surface_group_count=len(surface_group_summaries),
        curve_group_count=len(curve_group_summaries),
        interface_group_count=interface_group_count,
        boundary_group_count=boundary_group_count,
    )
    linear_constraints_summary: dict[str, ZoneLinearConstraintSummary] = {}
    for constraint in normalized_constraints:
        constraint_name = str(constraint.name)
        curve_tags = [int(tag) for tag in curve_tags_by_name.get(constraint_name, ())]
        curve_tag_set = set(curve_tags)
        linear_constraints_summary[constraint_name] = ZoneLinearConstraintSummary(
            provided=True,
            kind=str(constraint.kind),
            line_count=constraint.line_count,
            curve_count=len(curve_tags),
            embedded_surface_curve_pairs=int(
                constraint_embed_success_by_name.get(constraint_name, 0)
            ),
            embed_failures=int(constraint_embed_failures_by_name.get(constraint_name, 0)),
            refined_with_interface_field=bool(
                bool(refine_interfaces_value)
                and bool(curve_tag_set.intersection(refined_curve_tags))
            ),
            participates_in_refinement=bool(constraint.participates_in_refinement),
        )
    river_trace_summary = ZoneRiverTraceSummary.from_constraint_summary(
        linear_constraints_summary.get("river::trace"),
        provided=bool(river_trace is not None),
    )
    qa_checks = ZoneConformalQaChecks(
        coverage_gap=coverage_gap,
        coverage_tolerance=coverage_tolerance,
        coverage_within_tolerance=bool(coverage_gap <= coverage_tolerance),
        has_interface_groups=bool(interface_group_count > 0),
        has_zone_surface_groups=bool(len(surface_group_summaries) >= len(partition.zone_keys)),
    )
    summary = {
        "summary_schema_version": "zone_conformal_sidecar_v1",
        "output_mesh": str(output_path_obj),
        "mesh_kind": str(mesh.kind),
        "cell_type": str(mesh.cell_type),
        "n_nodes": int(mesh.n_nodes),
        "n_cells": int(mesh.n_cells),
        "n_partition_faces": int(partition.n_faces),
        "zone_keys": list(partition.zone_keys),
        "face_counts_by_zone": partition.face_counts_by_zone,
        "face_areas_by_zone": {
            key: round(float(value), 12) for key, value in partition.face_areas_by_zone.items()
        },
        "domain_area": round(float(domain_area_value), 12),
        "covered_area": round(float(covered_area_value), 12),
        "interface_group_count": int(interface_group_count),
        "boundary_group_count": int(boundary_group_count),
        "global_size": float(global_size_value),
        "min_size": None if min_size is None else float(min_size),
        "max_size": None if max_size is None else float(max_size),
        "algorithm": str(algorithm),
        "cleaning_diagnostics": cleaning_diagnostics_raw,
        "cleaning_summary": cleaning_summary.to_mapping(),
        "linear_constraints": {
            name: payload.to_mapping() for name, payload in linear_constraints_summary.items()
        },
        "river_trace": river_trace_summary.to_mapping(),
        "physical_groups_summary": physical_groups_summary.to_mapping(),
        "qa_checks": qa_checks.to_mapping(),
        "mesh_size_fields": {
            "interface_refinement": dict(mesh_size_fields_summary),
        },
        "surface_physical_groups": surface_group_summaries,
        "curve_physical_groups": curve_group_summaries,
    }
    if regional_background_summary is not None:
        summary["mesh_size_fields"]["regional_background"] = regional_background_summary
    if (max_size is None and effective_max_size > global_size_value) or (
        max_size is not None and effective_max_size > float(max_size)
    ):
        summary["effective_max_size"] = float(effective_max_size)
    if refinement_policy_summary is not None:
        summary["refinement_policy"] = dict(refinement_policy_summary)
    return summary

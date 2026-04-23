"""Candidate construction for local refinement filtering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from shapely.geometry import LineString

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._linework_matching import (
    segment_intersects_refinement_scope,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_contracts import (
    RefinementCurveCandidate,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementPolicy,
)


def refinement_family_from_group_name(group_name: str) -> str | None:
    """Map one physical-group name to the refinement family used by the policy."""

    name = str(group_name)
    if name == "river::trace":
        return "river"
    if name == "watershed::boundary":
        return "watershed_boundary"
    if name.startswith("interface::"):
        return "geology_interface"
    return None


def build_refinement_candidates(
    *,
    curve_tags_by_name: Mapping[str, Sequence[int]],
    curve_tag_to_segment: Mapping[int, LineString],
    refinement_scope_geometry,
    point_tolerance: float,
    policy: ZoneMeshingRefinementPolicy,
    default_interface_size: float,
    default_interface_distance: float,
    default_interface_sampling: int,
) -> tuple[RefinementCurveCandidate, ...]:
    """Build the scope-filtered refinement candidates consumed by the policy."""

    candidates: list[RefinementCurveCandidate] = []
    seen_curve_tags: set[int] = set()
    for group_name, curve_tags in curve_tags_by_name.items():
        family = refinement_family_from_group_name(str(group_name))
        if family is None:
            continue
        family_settings = policy.families.get(str(family))
        if family_settings is None:
            continue
        for raw_curve_tag in curve_tags:
            curve_tag = int(raw_curve_tag)
            if curve_tag in seen_curve_tags:
                continue
            segment = curve_tag_to_segment.get(curve_tag)
            if segment is None:
                continue
            if not segment_intersects_refinement_scope(
                segment=segment,
                scope_geometry=refinement_scope_geometry,
                tolerance=point_tolerance,
            ):
                continue
            seen_curve_tags.add(curve_tag)
            candidates.append(
                RefinementCurveCandidate(
                    curve_tag=curve_tag,
                    group_name=str(group_name),
                    family=str(family),
                    geometry=segment,
                    priority=int(family_settings.priority),
                    interface_size=float(
                        default_interface_size
                        if family_settings.interface_size is None
                        else family_settings.interface_size
                    ),
                    interface_distance=float(
                        default_interface_distance
                        if family_settings.interface_distance is None
                        else family_settings.interface_distance
                    ),
                    interface_sampling=int(
                        default_interface_sampling
                        if family_settings.interface_sampling is None
                        else family_settings.interface_sampling
                    ),
                )
            )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                int(candidate.priority),
                str(candidate.family),
                int(candidate.curve_tag),
            ),
            reverse=True,
        )
    )

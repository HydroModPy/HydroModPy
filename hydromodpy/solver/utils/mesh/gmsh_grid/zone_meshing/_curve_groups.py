"""Helpers dedicated to curve-group drafting and embedding.

These helpers stay internal to the zone-conformal mesher.  They separate the
responsibilities around:

- mapping registered curve tags back to simple geometries,
- deciding which physical curve group a segment belongs to,
- creating Gmsh physical groups,
- embedding internal constraint curves into partition faces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._linework_matching import (
    SurfaceEmbeddingLocator,
)


@dataclass
class ZoneCurveGroupDraft:
    """Mutable accumulator used while building physical curve groups."""

    group_kind: str
    zone_keys: tuple[str, ...]
    curve_tags: list[int]


def _group_kind_for_constraint_kind(kind: str) -> str:
    """Map one constraint semantic kind to the exported physical-group kind."""
    token = str(kind).strip().lower()
    if token == "river_trace":
        return "river_curve"
    return f"{token}_curve"


def _find_matching_constraint(
    *,
    segment: LineString | None,
    ordered_constraints: Sequence[Any],
    constraint_linework_by_name: Mapping[str, BaseGeometry],
    tolerance: float,
    segment_matches_linework_fn: Callable[..., bool],
) -> Any | None:
    """Return the first constraint whose linework matches the segment."""
    if segment is None:
        return None
    for constraint in ordered_constraints:
        linework = constraint_linework_by_name.get(str(constraint.name))
        if linework is None:
            continue
        if segment_matches_linework_fn(
            segment=segment,
            linework=linework,
            tolerance=tolerance,
        ):
            return constraint
    return None


def build_curve_tag_to_segment(
    *,
    line_registry: Mapping[tuple[tuple[float, float], tuple[float, float]], int],
) -> dict[int, LineString]:
    """Build one lightweight geometry lookup for already registered curve tags."""
    curve_tag_to_segment: dict[int, LineString] = {}
    for canonical, line_tag in line_registry.items():
        curve_tag_to_segment[int(line_tag)] = LineString(
            [
                (float(canonical[0][0]), float(canonical[0][1])),
                (float(canonical[1][0]), float(canonical[1][1])),
            ]
        )
    return curve_tag_to_segment


def draft_curve_groups(
    *,
    curve_usage: Mapping[int, set[str]],
    curve_tag_to_segment: Mapping[int, LineString],
    prepared_constraints: Sequence[Any],
    constraint_linework_by_name: Mapping[str, BaseGeometry],
    domain_boundary: BaseGeometry,
    tolerance: float,
    segment_matches_linework_fn: Callable[..., bool],
    build_curve_group_name_fn: Callable[..., tuple[str, str, tuple[str, ...]]],
) -> dict[str, ZoneCurveGroupDraft]:
    """Draft curve-group payloads before creating physical groups in Gmsh."""
    curve_groups: dict[str, ZoneCurveGroupDraft] = {}
    for curve_tag, zone_keys in sorted(curve_usage.items()):
        segment = curve_tag_to_segment.get(int(curve_tag))
        matched_constraint = _find_matching_constraint(
            segment=segment,
            ordered_constraints=prepared_constraints,
            constraint_linework_by_name=constraint_linework_by_name,
            tolerance=tolerance,
            segment_matches_linework_fn=segment_matches_linework_fn,
        )
        if matched_constraint is not None:
            name = str(matched_constraint.name)
            group_kind = _group_kind_for_constraint_kind(matched_constraint.kind)
            zone_names: tuple[str, ...] = ()
        else:
            is_boundary = segment_matches_linework_fn(
                segment=segment,
                linework=domain_boundary,
                tolerance=tolerance,
            )
            name, group_kind, zone_names = build_curve_group_name_fn(
                set(str(zone_key) for zone_key in zone_keys),
                is_boundary=is_boundary,
            )
        payload = curve_groups.setdefault(
            str(name),
            ZoneCurveGroupDraft(
                group_kind=str(group_kind),
                zone_keys=tuple(str(zone_key) for zone_key in zone_names),
                curve_tags=[],
            ),
        )
        payload.curve_tags.append(int(curve_tag))
    return curve_groups


def register_curve_physical_groups(
    *,
    gmsh,
    curve_groups: Mapping[str, ZoneCurveGroupDraft],
    physical_group_factory: Callable[..., Any],
) -> tuple[dict[str, list[int]], list[Any]]:
    """Create curve physical groups from drafted group payloads."""
    curve_tags_by_name: dict[str, list[int]] = {}
    physical_groups: list[Any] = []
    for name, payload in sorted(curve_groups.items()):
        curve_tags = sorted(set(int(tag) for tag in payload.curve_tags))
        curve_tags_by_name[str(name)] = curve_tags
        physical_tag = gmsh.model.addPhysicalGroup(1, curve_tags)
        gmsh.model.setPhysicalName(1, int(physical_tag), name)
        physical_groups.append(
            physical_group_factory(
                dimension=1,
                tag=int(physical_tag),
                name=str(name),
                group_kind=str(payload.group_kind),
                entity_tags=tuple(int(tag) for tag in sorted(curve_tags)),
                zone_keys=tuple(str(zone_key) for zone_key in payload.zone_keys),
            )
        )
    return curve_tags_by_name, physical_groups


def embed_constraint_curves(
    *,
    gmsh,
    prepared_constraints: Sequence[Any],
    curve_tags_by_name: Mapping[str, Sequence[int]],
    existing_curve_tags: set[int],
    curve_tag_to_segment: Mapping[int, LineString],
    surface_polygon_by_tag: Mapping[int, Polygon],
    tolerance: float,
    segment_matches_linework_fn: Callable[..., bool],
    success_by_name: dict[str, int],
    failures_by_name: dict[str, int],
    surface_locator: SurfaceEmbeddingLocator | None = None,
) -> None:
    """Embed non-boundary constraint curves into their matching partition faces."""
    for constraint in prepared_constraints:
        constraint_name = str(constraint.name)
        for curve_tag in curve_tags_by_name.get(constraint_name, []):
            if int(curve_tag) in existing_curve_tags:
                success_by_name[constraint_name] += 1
                continue
            segment = curve_tag_to_segment.get(int(curve_tag))
            if segment is None:
                failures_by_name[constraint_name] += 1
                continue
            embedded = False
            candidate_surface_tags = (
                () if surface_locator is None else surface_locator.locate_surface_tags(segment)
            )
            if candidate_surface_tags:
                for surface_tag in candidate_surface_tags:
                    try:
                        gmsh.model.mesh.embed(1, [int(curve_tag)], 2, int(surface_tag))
                        embedded = True
                        break
                    except Exception:
                        continue
            if not embedded:
                for surface_tag, surface_polygon in surface_polygon_by_tag.items():
                    if not segment_matches_linework_fn(
                        segment=segment,
                        linework=surface_polygon,
                        tolerance=tolerance,
                    ):
                        continue
                    try:
                        gmsh.model.mesh.embed(1, [int(curve_tag)], 2, int(surface_tag))
                        embedded = True
                        break
                    except Exception:
                        continue
            if embedded:
                success_by_name[constraint_name] += 1
            else:
                failures_by_name[constraint_name] += 1

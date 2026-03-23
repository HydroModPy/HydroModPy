"""Local hotspot-aware refinement filtering for mixed interface families.

The conformal mesher can generate one dense network of candidate refinement
curves that mixes geology interfaces, river traces, and watershed boundaries.
This module keeps the geometry constraints untouched while selectively thinning
the *refinement* contribution of low-priority families inside local hotspots.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._geometry_cleaning import (
    segment_intersects_refinement_scope,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing._refinement_grid import (
    RefinementGridCellId,
    build_refinement_grid,
)
from hydromodpy.solver.utils.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementFamilySettings,
    ZoneMeshingRefinementPolicy,
)

_REFINEMENT_FAMILIES = (
    "river",
    "geology_interface",
    "watershed_boundary",
)


@dataclass(frozen=True)
class RefinementCurveCandidate:
    """One scope-filtered curve that may contribute to the refinement field."""

    curve_tag: int
    group_name: str
    family: str
    geometry: LineString
    priority: int
    interface_size: float
    interface_distance: float
    interface_sampling: int

    @property
    def representative_point(self) -> Point:
        return self.geometry.interpolate(0.5, normalized=True)

    @property
    def length(self) -> float:
        return float(self.geometry.length)


@dataclass(frozen=True)
class RefinementHotspot:
    """One local region where the mixed refinement network is over budget."""

    hotspot_id: str
    reason: str
    center: tuple[float, float]
    radius: float
    member_curve_tags: tuple[int, ...]
    family_counts: Mapping[str, int]
    curve_count: int
    family_count: int
    max_node_degree: int
    short_segment_count: int
    min_cross_family_gap: float | None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "hotspot_id": str(self.hotspot_id),
            "reason": str(self.reason),
            "center": [float(self.center[0]), float(self.center[1])],
            "radius": float(self.radius),
            "member_curve_tags": [
                int(curve_tag) for curve_tag in self.member_curve_tags
            ],
            "family_counts": {
                str(key): int(value)
                for key, value in sorted(self.family_counts.items())
            },
            "curve_count": int(self.curve_count),
            "family_count": int(self.family_count),
            "max_node_degree": int(self.max_node_degree),
            "short_segment_count": int(self.short_segment_count),
            "min_cross_family_gap": (
                None
                if self.min_cross_family_gap is None
                else float(self.min_cross_family_gap)
            ),
        }


@dataclass(frozen=True)
class RefinementResolutionAction:
    """One local refinement-family demotion applied to resolve one hotspot."""

    hotspot_id: str
    family: str
    dropped_curve_tags: tuple[int, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "hotspot_id": str(self.hotspot_id),
            "family": str(self.family),
            "dropped_curve_tags": [
                int(curve_tag) for curve_tag in self.dropped_curve_tags
            ],
        }


@dataclass(frozen=True)
class RefinementPolicyResult:
    """Resolved refinement families after local hotspot filtering."""

    candidates: tuple[RefinementCurveCandidate, ...]
    active_curve_tags_by_family: Mapping[str, tuple[int, ...]]
    filtered_curve_tags_by_family: Mapping[str, tuple[int, ...]]
    detected_hotspots: tuple[RefinementHotspot, ...]
    remaining_hotspots: tuple[RefinementHotspot, ...]
    actions: tuple[RefinementResolutionAction, ...]

    @property
    def candidate_count(self) -> int:
        return int(len(self.candidates))

    @property
    def active_curve_count(self) -> int:
        return int(
            sum(len(tuple(curve_tags)) for curve_tags in self.active_curve_tags_by_family.values())
        )

    @property
    def filtered_curve_count(self) -> int:
        return int(
            sum(
                len(tuple(curve_tags))
                for curve_tags in self.filtered_curve_tags_by_family.values()
            )
        )

    def to_mapping(self) -> dict[str, Any]:
        family_counts_before = Counter(candidate.family for candidate in self.candidates)
        return {
            "candidate_curve_count": int(self.candidate_count),
            "active_curve_count": int(self.active_curve_count),
            "filtered_curve_count": int(self.filtered_curve_count),
            "family_curve_counts_before": {
                str(family): int(count)
                for family, count in sorted(family_counts_before.items())
            },
            "family_curve_counts_after": {
                str(family): int(len(tuple(curve_tags)))
                for family, curve_tags in sorted(self.active_curve_tags_by_family.items())
            },
            "family_curve_counts_filtered": {
                str(family): int(len(tuple(curve_tags)))
                for family, curve_tags in sorted(
                    self.filtered_curve_tags_by_family.items()
                )
            },
            "detected_hotspot_count": int(len(self.detected_hotspots)),
            "remaining_hotspot_count": int(len(self.remaining_hotspots)),
            "hotspots_detected": [
                hotspot.to_mapping() for hotspot in self.detected_hotspots
            ],
            "hotspots_remaining": [
                hotspot.to_mapping() for hotspot in self.remaining_hotspots
            ],
            "actions": [action.to_mapping() for action in self.actions],
        }


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
    """Return one candidate per family-tag pair eligible for local filtering."""

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


def apply_local_refinement_policy(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> RefinementPolicyResult:
    """Resolve local hotspots by demoting low-priority refinement families."""

    candidate_by_tag = {
        int(candidate.curve_tag): candidate for candidate in candidates
    }
    active_tags: set[int] = {
        int(candidate.curve_tag)
        for candidate in candidates
        if bool(policy.families.get(candidate.family, _disabled_family()).enabled)
    }
    detected_hotspots = detect_refinement_hotspots(
        candidates=tuple(candidate_by_tag[curve_tag] for curve_tag in sorted(active_tags)),
        policy=policy,
    )
    actions: list[RefinementResolutionAction] = []

    for _iteration in range(3):
        changed = False
        current_candidates = tuple(
            candidate_by_tag[curve_tag] for curve_tag in sorted(active_tags)
        )
        current_hotspots = detect_refinement_hotspots(
            candidates=current_candidates,
            policy=policy,
        )
        if not current_hotspots:
            break
        for hotspot in current_hotspots:
            local_active = [
                candidate_by_tag[curve_tag]
                for curve_tag in hotspot.member_curve_tags
                if curve_tag in active_tags
            ]
            local_active = _sort_candidates_by_family_priority(local_active)
            while _hotspot_exceeds_budget(
                candidates=local_active,
                center=hotspot.center,
                policy=policy,
            ):
                removable_family = _lowest_priority_family(local_active, policy)
                if removable_family is None:
                    break
                dropped_curve_tags = tuple(
                    sorted(
                        int(candidate.curve_tag)
                        for candidate in local_active
                        if candidate.family == removable_family
                    )
                )
                if not dropped_curve_tags:
                    break
                for curve_tag in dropped_curve_tags:
                    active_tags.discard(int(curve_tag))
                actions.append(
                    RefinementResolutionAction(
                        hotspot_id=hotspot.hotspot_id,
                        family=str(removable_family),
                        dropped_curve_tags=dropped_curve_tags,
                    )
                )
                changed = True
                local_active = [
                    candidate_by_tag[curve_tag]
                    for curve_tag in hotspot.member_curve_tags
                    if curve_tag in active_tags
                ]
                local_active = _sort_candidates_by_family_priority(local_active)
        if not changed:
            break

    remaining_hotspots = detect_refinement_hotspots(
        candidates=tuple(candidate_by_tag[curve_tag] for curve_tag in sorted(active_tags)),
        policy=policy,
    )
    return RefinementPolicyResult(
        candidates=tuple(candidates),
        active_curve_tags_by_family=_curve_tags_by_family(
            tuple(candidate_by_tag[curve_tag] for curve_tag in sorted(active_tags))
        ),
        filtered_curve_tags_by_family=_curve_tags_by_family(
            tuple(
                candidate
                for candidate in candidates
                if int(candidate.curve_tag) not in active_tags
            )
        ),
        detected_hotspots=detected_hotspots,
        remaining_hotspots=remaining_hotspots,
        actions=tuple(actions),
    )


def detect_refinement_hotspots(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> tuple[RefinementHotspot, ...]:
    """Return local hotspots where the mixed refinement network exceeds budget."""
    if str(policy.mode) == "grid_local_budget":
        return _detect_refinement_hotspots_grid(
            candidates=candidates,
            policy=policy,
        )
    return _detect_refinement_hotspots_pairwise(
        candidates=candidates,
        policy=policy,
    )


def _detect_refinement_hotspots_pairwise(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> tuple[RefinementHotspot, ...]:
    """Return hotspots using the original pairwise/global search strategy."""
    if not candidates:
        return ()

    hotspots: dict[tuple[float, float], RefinementHotspot] = {}
    radius = float(
        policy.hotspot.radius
        if policy.hotspot.radius is not None
        else max(
            float(candidate.interface_distance)
            for candidate in candidates
        )
    )

    for center, reason in _iter_hotspot_centers(candidates=candidates, policy=policy):
        local_candidates = _local_candidates(
            candidates=candidates,
            center=center,
            radius=radius,
        )
        if not _hotspot_exceeds_budget(
            candidates=local_candidates,
            center=center,
            policy=policy,
        ):
            continue
        metrics = _evaluate_local_metrics(
            candidates=local_candidates,
            center=center,
            radius=radius,
            policy=policy,
        )
        key = (round(float(center[0]), 3), round(float(center[1]), 3))
        existing = hotspots.get(key)
        candidate_hotspot = RefinementHotspot(
            hotspot_id=f"hotspot_{len(hotspots) + 1}",
            reason=str(reason),
            center=(float(center[0]), float(center[1])),
            radius=float(radius),
            member_curve_tags=tuple(
                sorted(int(candidate.curve_tag) for candidate in local_candidates)
            ),
            family_counts=dict(metrics["family_counts"]),
            curve_count=int(metrics["curve_count"]),
            family_count=int(metrics["family_count"]),
            max_node_degree=int(metrics["max_node_degree"]),
            short_segment_count=int(metrics["short_segment_count"]),
            min_cross_family_gap=metrics["min_cross_family_gap"],
        )
        if existing is None or _hotspot_sort_key(candidate_hotspot) > _hotspot_sort_key(
            existing
        ):
            hotspots[key] = candidate_hotspot

    return tuple(
        sorted(hotspots.values(), key=_hotspot_sort_key, reverse=True)
    )


def _detect_refinement_hotspots_grid(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> tuple[RefinementHotspot, ...]:
    """Return hotspots using one regular grid and local neighborhoods only."""
    if not candidates:
        return ()

    cell_size = _resolve_grid_cell_size(candidates=candidates, policy=policy)
    grid = build_refinement_grid(
        candidates=candidates,
        cell_size=float(cell_size),
    )
    if not grid.active_cell_ids:
        return ()

    candidate_by_tag = {
        int(candidate.curve_tag): candidate for candidate in candidates
    }
    neighborhoods: dict[tuple[int, ...], tuple[RefinementGridCellId, ...]] = defaultdict(tuple)
    neighborhood_curve_tags_by_cell: dict[RefinementGridCellId, tuple[int, ...]] = {}
    for cell_id in grid.active_cell_ids:
        neighborhood_curve_tags = grid.collect_neighborhood_curve_tags(
            cell_id,
            rings=int(policy.grid.neighborhood_rings),
        )
        if not neighborhood_curve_tags:
            continue
        neighborhood_curve_tags_by_cell[cell_id] = neighborhood_curve_tags
        neighborhoods.setdefault(neighborhood_curve_tags, ())
        neighborhoods[neighborhood_curve_tags] = tuple(
            sorted(
                set(neighborhoods[neighborhood_curve_tags]) | {cell_id},
                key=lambda item: (int(item.row), int(item.col)),
            )
        )

    hotspot_candidates: list[RefinementHotspot] = []
    for member_curve_tags, seed_cells in neighborhoods.items():
        local_candidates = [
            candidate_by_tag[int(curve_tag)]
            for curve_tag in member_curve_tags
            if int(curve_tag) in candidate_by_tag
        ]
        if not local_candidates:
            continue
        center = _cells_center(
            grid=grid,
            cell_ids=seed_cells,
        )
        radius = _grid_neighborhood_radius(
            cell_size=float(grid.cell_size),
            rings=int(policy.grid.neighborhood_rings),
        )
        metrics = _evaluate_local_metrics(
            candidates=local_candidates,
            center=center,
            radius=radius,
            policy=policy,
        )
        if not _metrics_exceed_budget(metrics=metrics, policy=policy):
            continue
        hotspot_candidates.append(
            RefinementHotspot(
                hotspot_id="",
                reason=_hotspot_reason_from_metrics(metrics=metrics, policy=policy),
                center=(float(center[0]), float(center[1])),
                radius=float(radius),
                member_curve_tags=tuple(
                    sorted(int(candidate.curve_tag) for candidate in local_candidates)
                ),
                family_counts=dict(metrics["family_counts"]),
                curve_count=int(metrics["curve_count"]),
                family_count=int(metrics["family_count"]),
                max_node_degree=int(metrics["max_node_degree"]),
                short_segment_count=int(metrics["short_segment_count"]),
                min_cross_family_gap=metrics["min_cross_family_gap"],
            )
        )

    hotspot_candidates.sort(key=_hotspot_sort_key, reverse=True)
    return tuple(
        RefinementHotspot(
            hotspot_id=f"hotspot_{index + 1}",
            reason=hotspot.reason,
            center=hotspot.center,
            radius=hotspot.radius,
            member_curve_tags=hotspot.member_curve_tags,
            family_counts=hotspot.family_counts,
            curve_count=hotspot.curve_count,
            family_count=hotspot.family_count,
            max_node_degree=hotspot.max_node_degree,
            short_segment_count=hotspot.short_segment_count,
            min_cross_family_gap=hotspot.min_cross_family_gap,
        )
        for index, hotspot in enumerate(hotspot_candidates)
    )


def _curve_tags_by_family(
    candidates: Sequence[RefinementCurveCandidate],
) -> dict[str, tuple[int, ...]]:
    grouped: dict[str, list[int]] = {family: [] for family in _REFINEMENT_FAMILIES}
    for candidate in candidates:
        grouped.setdefault(str(candidate.family), []).append(int(candidate.curve_tag))
    return {
        family: tuple(sorted(set(int(curve_tag) for curve_tag in curve_tags)))
        for family, curve_tags in sorted(grouped.items())
    }


def _sort_candidates_by_family_priority(
    candidates: Sequence[RefinementCurveCandidate],
) -> list[RefinementCurveCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            int(candidate.priority),
            str(candidate.family),
            int(candidate.curve_tag),
        ),
        reverse=True,
    )


def _lowest_priority_family(
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> str | None:
    present_families = {str(candidate.family) for candidate in candidates}
    if len(present_families) <= 1:
        return None
    family_candidates = [
        family_name
        for family_name in present_families
        if bool(policy.families.get(family_name, _disabled_family()).enabled)
    ]
    if not family_candidates:
        return None
    return min(
        family_candidates,
        key=lambda family_name: (
            int(policy.families[family_name].priority),
            str(family_name),
        ),
    )


def _iter_hotspot_centers(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> tuple[tuple[tuple[float, float], str], ...]:
    centers: list[tuple[tuple[float, float], str]] = []
    node_map = _node_map(candidates)

    for node_xy, node_candidates in node_map.items():
        family_count = len({candidate.family for candidate in node_candidates})
        if family_count > 1 and len(node_candidates) > int(policy.hotspot.max_node_degree):
            centers.append((node_xy, "mixed_node_degree"))

    for index, candidate in enumerate(candidates):
        midpoint = candidate.representative_point
        center = (float(midpoint.x), float(midpoint.y))
        local_candidates = _local_candidates(
            candidates=candidates,
            center=center,
            radius=float(
                policy.hotspot.radius
                if policy.hotspot.radius is not None
                else candidate.interface_distance
            ),
        )
        family_count = len({local_candidate.family for local_candidate in local_candidates})
        if (
            family_count > 1
            and len(local_candidates) > int(policy.hotspot.max_curve_count)
        ):
            centers.append((center, "local_curve_density"))
        for other in candidates[index + 1 :]:
            if candidate.family == other.family:
                continue
            gap = float(candidate.geometry.distance(other.geometry))
            if gap < float(policy.hotspot.min_gap):
                p0, p1 = nearest_points(candidate.geometry, other.geometry)
                centers.append(
                    (
                        (
                            float((p0.x + p1.x) * 0.5),
                            float((p0.y + p1.y) * 0.5),
                        ),
                        "cross_family_gap",
                    )
                )

    return tuple(centers)


def _local_candidates(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    center: tuple[float, float],
    radius: float,
) -> list[RefinementCurveCandidate]:
    center_point = Point(float(center[0]), float(center[1]))
    return [
        candidate
        for candidate in candidates
        if float(center_point.distance(candidate.geometry)) <= float(radius)
    ]


def _hotspot_exceeds_budget(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    center: tuple[float, float],
    policy: ZoneMeshingRefinementPolicy,
) -> bool:
    metrics = _evaluate_local_metrics(
        candidates=candidates,
        center=center,
        radius=float(
            policy.hotspot.radius
            if policy.hotspot.radius is not None
            else max(
                [float(candidate.interface_distance) for candidate in candidates]
                or [0.0]
            )
        ),
        policy=policy,
    )
    return _metrics_exceed_budget(metrics=metrics, policy=policy)


def _metrics_exceed_budget(
    *,
    metrics: Mapping[str, Any],
    policy: ZoneMeshingRefinementPolicy,
) -> bool:
    family_count = int(metrics["family_count"])
    if family_count <= 1:
        return False
    if int(metrics["curve_count"]) > int(policy.hotspot.max_curve_count):
        return True
    if family_count > int(policy.hotspot.max_family_count):
        return True
    if int(metrics["max_node_degree"]) > int(policy.hotspot.max_node_degree):
        return True
    if int(metrics["short_segment_count"]) > int(policy.hotspot.max_short_segment_count):
        return True
    min_gap = metrics["min_cross_family_gap"]
    if min_gap is not None and float(min_gap) < float(policy.hotspot.min_gap):
        return True
    return False


def _evaluate_local_metrics(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    center: tuple[float, float],
    radius: float,
    policy: ZoneMeshingRefinementPolicy,
) -> dict[str, Any]:
    family_counts = Counter(candidate.family for candidate in candidates)
    short_segment_count = int(
        sum(
            1
            for candidate in candidates
            if candidate.length <= float(policy.hotspot.short_segment_length)
        )
    )
    node_degree = _local_max_node_degree(candidates)
    min_cross_family_gap = _maybe_min_cross_family_gap(
        candidates=candidates,
        policy=policy,
    )
    return {
        "center": (float(center[0]), float(center[1])),
        "radius": float(radius),
        "curve_count": int(len(candidates)),
        "family_count": int(len(family_counts)),
        "family_counts": dict(family_counts),
        "short_segment_count": short_segment_count,
        "max_node_degree": int(node_degree),
        "min_cross_family_gap": min_cross_family_gap,
    }


def _local_max_node_degree(candidates: Sequence[RefinementCurveCandidate]) -> int:
    node_map = _node_map(candidates)
    if not node_map:
        return 0
    return int(max(len(node_candidates) for node_candidates in node_map.values()))


def _resolve_grid_cell_size(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> float:
    cell_size = policy.grid.cell_size
    if cell_size is not None and float(cell_size) > 0.0:
        return float(cell_size)
    return max(
        max(float(candidate.interface_distance) for candidate in candidates) * 0.5,
        max(float(candidate.interface_size) for candidate in candidates),
    )


def _cells_center(
    *,
    grid,
    cell_ids: Sequence[RefinementGridCellId],
) -> tuple[float, float]:
    if not cell_ids:
        xmin, ymin, xmax, ymax = grid.bounds
        return (float((xmin + xmax) * 0.5), float((ymin + ymax) * 0.5))
    xs: list[float] = []
    ys: list[float] = []
    xmin, ymin, _xmax, _ymax = grid.bounds
    for cell_id in cell_ids:
        xs.append(float(xmin) + (float(cell_id.col) + 0.5) * float(grid.cell_size))
        ys.append(float(ymin) + (float(cell_id.row) + 0.5) * float(grid.cell_size))
    return (float(sum(xs) / len(xs)), float(sum(ys) / len(ys)))


def _grid_neighborhood_radius(
    *,
    cell_size: float,
    rings: int,
) -> float:
    return float(cell_size) * (float(rings) + 0.75)


def _maybe_min_cross_family_gap(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> float | None:
    if not candidates:
        return None
    if str(policy.mode) == "grid_local_budget":
        if not bool(policy.grid.enable_exact_gap_check):
            return None
        if len(candidates) > int(policy.grid.max_exact_gap_candidates):
            return None
    return _min_cross_family_gap(candidates)


def _node_map(
    candidates: Sequence[RefinementCurveCandidate],
) -> dict[tuple[float, float], list[RefinementCurveCandidate]]:
    node_map: dict[tuple[float, float], list[RefinementCurveCandidate]] = defaultdict(list)
    for candidate in candidates:
        coords = list(candidate.geometry.coords)
        if len(coords) < 2:
            continue
        for xy in (coords[0], coords[-1]):
            key = (round(float(xy[0]), 9), round(float(xy[1]), 9))
            node_map[key].append(candidate)
    return node_map


def _min_cross_family_gap(
    candidates: Sequence[RefinementCurveCandidate],
) -> float | None:
    min_gap: float | None = None
    for index, candidate in enumerate(candidates):
        for other in candidates[index + 1 :]:
            if candidate.family == other.family:
                continue
            gap = float(candidate.geometry.distance(other.geometry))
            if min_gap is None or gap < min_gap:
                min_gap = gap
    return min_gap


def _hotspot_reason_from_metrics(
    *,
    metrics: Mapping[str, Any],
    policy: ZoneMeshingRefinementPolicy,
) -> str:
    if int(metrics["curve_count"]) > int(policy.hotspot.max_curve_count):
        return "local_curve_density"
    if int(metrics["family_count"]) > int(policy.hotspot.max_family_count):
        return "local_family_mix"
    if int(metrics["max_node_degree"]) > int(policy.hotspot.max_node_degree):
        return "mixed_node_degree"
    if int(metrics["short_segment_count"]) > int(policy.hotspot.max_short_segment_count):
        return "short_segments"
    min_gap = metrics["min_cross_family_gap"]
    if min_gap is not None and float(min_gap) < float(policy.hotspot.min_gap):
        return "cross_family_gap"
    return "local_budget"


def _hotspot_sort_key(hotspot: RefinementHotspot) -> tuple[int, int, int, float]:
    min_gap = (
        1.0e12
        if hotspot.min_cross_family_gap is None
        else float(hotspot.min_cross_family_gap)
    )
    return (
        int(hotspot.curve_count),
        int(hotspot.max_node_degree),
        int(hotspot.family_count),
        -float(min_gap),
    )


def _disabled_family() -> ZoneMeshingRefinementFamilySettings:
    return ZoneMeshingRefinementFamilySettings(
        enabled=False,
        priority=-10_000,
        interface_size=None,
        interface_distance=None,
        interface_sampling=None,
    )


__all__ = [
    "RefinementCurveCandidate",
    "RefinementHotspot",
    "RefinementPolicyResult",
    "RefinementResolutionAction",
    "apply_local_refinement_policy",
    "build_refinement_candidates",
    "detect_refinement_hotspots",
    "refinement_family_from_group_name",
]

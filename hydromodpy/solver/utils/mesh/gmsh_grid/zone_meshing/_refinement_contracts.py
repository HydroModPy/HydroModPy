"""Data contracts for local refinement filtering.

These dataclasses capture the refinement candidates, detected hotspots, local
actions, and final policy result. They are kept separate from the orchestration
logic so the pairwise and grid-based algorithms can share the same payloads.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from shapely.geometry import LineString, Point

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
            "member_curve_tags": [int(curve_tag) for curve_tag in self.member_curve_tags],
            "family_counts": {
                str(key): int(value) for key, value in sorted(self.family_counts.items())
            },
            "curve_count": int(self.curve_count),
            "family_count": int(self.family_count),
            "max_node_degree": int(self.max_node_degree),
            "short_segment_count": int(self.short_segment_count),
            "min_cross_family_gap": (
                None if self.min_cross_family_gap is None else float(self.min_cross_family_gap)
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
            "dropped_curve_tags": [int(curve_tag) for curve_tag in self.dropped_curve_tags],
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
                len(tuple(curve_tags)) for curve_tags in self.filtered_curve_tags_by_family.values()
            )
        )

    def to_mapping(self) -> dict[str, Any]:
        family_counts_before = Counter(candidate.family for candidate in self.candidates)
        return {
            "candidate_curve_count": int(self.candidate_count),
            "active_curve_count": int(self.active_curve_count),
            "filtered_curve_count": int(self.filtered_curve_count),
            "family_curve_counts_before": {
                str(family): int(count) for family, count in sorted(family_counts_before.items())
            },
            "family_curve_counts_after": {
                str(family): int(len(tuple(curve_tags)))
                for family, curve_tags in sorted(self.active_curve_tags_by_family.items())
            },
            "family_curve_counts_filtered": {
                str(family): int(len(tuple(curve_tags)))
                for family, curve_tags in sorted(self.filtered_curve_tags_by_family.items())
            },
            "detected_hotspot_count": int(len(self.detected_hotspots)),
            "remaining_hotspot_count": int(len(self.remaining_hotspots)),
            "hotspots_detected": [hotspot.to_mapping() for hotspot in self.detected_hotspots],
            "hotspots_remaining": [hotspot.to_mapping() for hotspot in self.remaining_hotspots],
            "actions": [action.to_mapping() for action in self.actions],
        }

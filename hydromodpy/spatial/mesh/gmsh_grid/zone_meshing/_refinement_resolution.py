"""Resolution helpers for local refinement filtering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_contracts import (
    _REFINEMENT_FAMILIES,
    RefinementCurveCandidate,
    RefinementHotspot,
    RefinementPolicyResult,
    RefinementResolutionAction,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._refinement_hotspots import (
    _hotspot_exceeds_budget,
    detect_refinement_hotspots,
)
from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing.config import (
    ZoneMeshingRefinementFamilySettings,
    ZoneMeshingRefinementPolicy,
)


def apply_local_refinement_policy(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> RefinementPolicyResult:
    """Resolve local hotspots by demoting low-priority refinement families."""

    candidate_by_tag = _candidate_lookup(candidates)
    active_tags = _enabled_curve_tags(candidates=candidates, policy=policy)
    detected_hotspots = detect_refinement_hotspots(
        candidates=_candidates_from_tags(
            candidate_by_tag=candidate_by_tag,
            curve_tags=active_tags,
        ),
        policy=policy,
    )
    actions: list[RefinementResolutionAction] = []

    for _iteration in range(3):
        changed = False
        current_candidates = _candidates_from_tags(
            candidate_by_tag=candidate_by_tag,
            curve_tags=active_tags,
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
                _discard_curve_tags(
                    active_tags=active_tags,
                    curve_tags=dropped_curve_tags,
                )
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
        candidates=_candidates_from_tags(
            candidate_by_tag=candidate_by_tag,
            curve_tags=active_tags,
        ),
        policy=policy,
    )
    return _build_policy_result(
        candidates=candidates,
        candidate_by_tag=candidate_by_tag,
        active_tags=active_tags,
        detected_hotspots=detected_hotspots,
        remaining_hotspots=remaining_hotspots,
        actions=actions,
    )


def _curve_tags_by_family(
    candidates: Sequence[RefinementCurveCandidate],
) -> dict[str, tuple[int, ...]]:
    """Return one stable family -> curve-tags mapping for summaries and Gmsh."""
    grouped: dict[str, list[int]] = {family: [] for family in _REFINEMENT_FAMILIES}
    for candidate in candidates:
        grouped.setdefault(str(candidate.family), []).append(int(candidate.curve_tag))
    return {
        family: tuple(sorted(set(int(curve_tag) for curve_tag in curve_tags)))
        for family, curve_tags in sorted(grouped.items())
    }


def _candidate_lookup(
    candidates: Sequence[RefinementCurveCandidate],
) -> dict[int, RefinementCurveCandidate]:
    """Index candidates by curve tag once so later iterations stay readable."""
    return {int(candidate.curve_tag): candidate for candidate in candidates}


def _enabled_curve_tags(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    policy: ZoneMeshingRefinementPolicy,
) -> set[int]:
    """Return the initial active tag set allowed by the family policy."""
    return {
        int(candidate.curve_tag)
        for candidate in candidates
        if bool(policy.families.get(candidate.family, _disabled_family()).enabled)
    }


def _candidates_from_tags(
    *,
    candidate_by_tag: Mapping[int, RefinementCurveCandidate],
    curve_tags: Sequence[int] | set[int],
) -> tuple[RefinementCurveCandidate, ...]:
    """Materialize one sorted candidate tuple from the active curve-tag set."""
    return tuple(
        candidate_by_tag[int(curve_tag)]
        for curve_tag in sorted(int(curve_tag) for curve_tag in curve_tags)
    )


def _discard_curve_tags(
    *,
    active_tags: set[int],
    curve_tags: Sequence[int],
) -> None:
    """Remove one batch of curve tags from the active set in place."""
    for curve_tag in curve_tags:
        active_tags.discard(int(curve_tag))


def _build_policy_result(
    *,
    candidates: Sequence[RefinementCurveCandidate],
    candidate_by_tag: Mapping[int, RefinementCurveCandidate],
    active_tags: set[int],
    detected_hotspots: Sequence[RefinementHotspot],
    remaining_hotspots: Sequence[RefinementHotspot],
    actions: Sequence[RefinementResolutionAction],
) -> RefinementPolicyResult:
    """Assemble the final policy payload once active tags have been resolved."""
    active_candidates = _candidates_from_tags(
        candidate_by_tag=candidate_by_tag,
        curve_tags=active_tags,
    )
    filtered_candidates = tuple(
        candidate for candidate in candidates if int(candidate.curve_tag) not in active_tags
    )
    return RefinementPolicyResult(
        candidates=tuple(candidates),
        active_curve_tags_by_family=_curve_tags_by_family(active_candidates),
        filtered_curve_tags_by_family=_curve_tags_by_family(filtered_candidates),
        detected_hotspots=tuple(detected_hotspots),
        remaining_hotspots=tuple(remaining_hotspots),
        actions=tuple(actions),
    )


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


def _disabled_family() -> ZoneMeshingRefinementFamilySettings:
    return ZoneMeshingRefinementFamilySettings(
        enabled=False,
        priority=-10_000,
        interface_size=None,
        interface_distance=None,
        interface_sampling=None,
    )

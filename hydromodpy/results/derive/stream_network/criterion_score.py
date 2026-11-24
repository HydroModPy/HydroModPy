"""Turn the simulated network of one run into the distances of the network criterion.

A calibration trial and a stored run score the network with these two functions,
so the number a run gives after the fact is the number its trial gave. Both read
geometries already built on the maps and the flow already counted:
:func:`score_one_state` reads one release field, :func:`score_extent` reads the
yearly flow counts of the two-bound mode. The trial counts its stack in memory
(:func:`hydromodpy.catchment.stream_network.extent.yearly_flow_counts`), a stored
run reads its store by blocks
(:func:`hydromodpy.results.derive.stream_network.run_extent.block_flow_counts`), and
the counts are integers, so both reach the same masks.

The value is the pair ``(D_so, D_os)`` of the bound in the cost, or four values
with two bounds. Every other number travels in the components, unprefixed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from hydromodpy.catchment.stream_network.cost import (
    MAXIMAL_SUFFIX,
    MINIMAL_SUFFIX,
    VALIDATION_SUFFIX,
    SeepageDistanceResult,
    Weighting,
    score_on_geometry,
    weighted_pair,
    with_suffix,
)
from hydromodpy.catchment.stream_network.extent import (
    Bound,
    CalendarYears,
    YearlyFlowCounts,
    extent_masks,
)
from hydromodpy.catchment.stream_network.geometry import NetworkGeometry
from hydromodpy.catchment.stream_network.network import build_simulated_network
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scoring.stream_defaults import VisibleFlow

logger = get_logger(__name__)

__all__ = (
    "SHARED_GEOMETRY_KEYS",
    "ScoredMap",
    "score_extent",
    "score_one_state",
)

SHARED_GEOMETRY_KEYS = ("R_mean_m_s", "catchment_mismatch", "basin_mismatch")
"""Geometry diagnostics that depend on the topography alone, the same for both maps."""


@dataclass(frozen=True, slots=True)
class ScoredMap:
    """One map a bound is scored against, and what qualifies the map itself.

    ``facts`` are published beside the distances of the map: whether it was cut to
    the catchment, how many cells it holds, how many reaches fell back on a midpoint.
    """

    geometry: NetworkGeometry
    facts: Mapping[str, float]


def _map_components(scored: SeepageDistanceResult, scored_map: ScoredMap) -> dict[str, float]:
    """Return what one map was scored to, and what qualifies the map itself."""
    return {
        **scored.components,
        **{
            key: value
            for key, value in scored_map.geometry.diagnostics.items()
            if key not in SHARED_GEOMETRY_KEYS
        },
        **scored_map.facts,
    }


def score_one_state(
    release: np.ndarray,
    maximal: ScoredMap,
    minimal: ScoredMap | None,
    *,
    calibrate_on_complete: bool,
    weighting: Weighting,
    validity_length_m: float | None,
) -> tuple[list[float], dict[str, float]]:
    """Score the one state a steady run holds, as the papers do.

    Without a permanent map the state is compared to the complete map, the only
    one. With both, ``calibrate_on_complete`` names the map in the cost. The other
    map is scored at the same state as a validation that never reaches the cost.
    ``validity_length_m`` is None for ``"auto"``.
    """
    geometry = maximal.geometry
    simulated = build_simulated_network(
        release,
        threshold_m3_s=geometry.threshold_m3_s,
        metric=geometry.metric,
    )
    options = {"weighting": weighting, "validity_length_m": validity_length_m}
    if minimal is None:
        scored = score_on_geometry(simulated, geometry, **options)
        bound = _map_components(scored, maximal)
        return weighted_pair(scored), {**bound, **with_suffix(bound, MAXIMAL_SUFFIX)}

    cost, checked, cost_suffix, checked_suffix = (
        (maximal, minimal, MAXIMAL_SUFFIX, MINIMAL_SUFFIX)
        if calibrate_on_complete
        else (minimal, maximal, MINIMAL_SUFFIX, MAXIMAL_SUFFIX)
    )
    scored = score_on_geometry(simulated, cost.geometry, **options)
    bound = _map_components(scored, cost)
    validation = _map_components(score_on_geometry(simulated, checked.geometry, **options), checked)
    return weighted_pair(scored), {
        **bound,
        **with_suffix(bound, cost_suffix),
        **with_suffix(validation, f"{checked_suffix}{VALIDATION_SUFFIX}"),
    }


def score_extent(
    name: str,
    counts: YearlyFlowCounts,
    years: CalendarYears,
    maximal: ScoredMap,
    minimal: ScoredMap | None,
    *,
    maximal_flowing_steps: int,
    minimal_dry_steps: int,
    year_quorum: float,
    weights: tuple[float, float],
    weighting: Weighting,
    validity_length_m: float | None,
    step_days: float,
    visible: VisibleFlow,
) -> tuple[list[float], dict[str, float]]:
    """Score the yearly extent masks of a transient run against one or two maps.

    ``counts`` are the flowing and seepage counts of each scored year of ``years``.
    The maximal mask is scored against the maximal map, the minimal mask against
    the minimal map when there is one, and each year's masks the same way as a
    diagnostic. With one bound the unsuffixed components carry it; with two, only
    the suffixed ones exist and the pair holds both, each weighted by
    ``weights = (permanent, complete)``. ``name`` names the output in the log.
    """
    masks = extent_masks(
        counts,
        maximal_flowing_steps=maximal_flowing_steps,
        minimal_dry_steps=minimal_dry_steps,
        year_quorum=year_quorum,
    )
    options = {"weighting": weighting, "validity_length_m": validity_length_m}
    permanent_weight, complete_weight = weights
    bounds: list[tuple[Bound, ScoredMap, str, float]] = [
        ("maximal", maximal, MAXIMAL_SUFFIX, float(complete_weight))
    ]
    if minimal is not None:
        bounds.insert(0, ("minimal", minimal, MINIMAL_SUFFIX, float(permanent_weight)))
    threshold = maximal.geometry.threshold_m3_s
    pair: list[float] = []
    components: dict[str, float] = {}
    for bound, scored_map, suffix, weight in bounds:
        scored = score_on_geometry(
            masks.network(bound, threshold_m3_s=threshold), scored_map.geometry, **options
        )
        described = _map_components(scored, scored_map)
        if len(bounds) == 1:
            pair.extend(weighted_pair(scored))
            components.update(described)
        else:
            pair.extend(weighted_pair(scored, weight))
            components[f"weight{suffix}"] = weight
        components.update(with_suffix(described, suffix))
        for year in masks.years:
            yearly = score_on_geometry(
                masks.network(bound, threshold_m3_s=threshold, year=year),
                scored_map.geometry,
                **options,
            )
            components[f"J_signed{suffix}_y{year}"] = float(yearly.signed_gap)
            components[f"n_network_sim{suffix}_y{year}"] = yearly.components["n_network_sim"]
    components.update(
        {
            **{f"year_scored_y{year}": 1.0 for year in years.years},
            **{f"year_scored_y{year}": 0.0 for year in (*years.incomplete, *years.outside_window)},
            "n_years_scored": float(len(masks.years)),
            "n_years_outside_window": float(len(years.outside_window)),
            "n_years_required": float(masks.n_years_required),
            "first_year_scored": float(masks.years[0]),
            "last_year_scored": float(masks.years[-1]),
            "n_steps_min_per_year": float(years.n_steps.min()),
            "year_quorum": float(year_quorum),
            "maximal_flowing_steps": float(maximal_flowing_steps),
            "minimal_dry_steps": float(minimal_dry_steps),
            "step_days": float(step_days),
            "visible_flow_m3_s": visible.discharge_m3_s,
            "visible_flow_outlet_share": visible.outlet_share,
        }
    )
    logger.info(
        "Output %s: %d bound(s) scored over %d complete year(s) %s%s, a cell entering a "
        "mask in %d of them; maximal mask %d cell(s), minimal mask %d cell(s); flowing "
        "means the closure of the seepage carrying at least %s.",
        name,
        len(bounds),
        len(masks.years),
        ", ".join(map(str, masks.years)),
        (
            f" (outside the window: {', '.join(map(str, years.outside_window))})"
            if years.outside_window
            else ""
        ),
        masks.n_years_required,
        int(masks.maximal.sum()),
        int(masks.minimal.sum()),
        visible.label(),
    )
    return pair, components

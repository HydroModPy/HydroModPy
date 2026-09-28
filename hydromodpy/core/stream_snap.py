"""Snap the mapped stream network onto the talwegs of the criterion graph.

A mapped network is surveyed independently of the DEM, so its cells rarely sit
on the talwegs the model top descends. The distance criterion then measures
that misregistration on top of the hydrogeology. Snapping projects the map onto
what the model can represent, a union of descent paths on its own graph, and
publishes what the projection cost. It never corrects the observation silently:
the displacement of every cell, the cells it could not place, and the floor
``F`` (the ``Doptim`` of the snapped map against the raw one) are published.

The algorithm is flow-accumulation guided snapping on the criterion graph, in
the topological order of the mapped network from downstream to upstream:

1. the mapped cells of the catchment are grouped into connected pieces on the
   criterion neighbour graph, and each piece is rooted at its lowest cell;
2. the pieces are walked by a priority flood from their roots along the map
   itself, the most accumulated mapped cell first, so a main stem is processed
   before the tributaries that join it;
3. each mapped cell moves, within the radius, to the most accumulated model
   cell that is not yet taken and whose receiver is already attached. The
   outlet is attached from the start, and so are the water bodies, which the
   criterion also counts as surface water. That rule is what keeps every
   snapped cell continuous to the outlet;
4. a cell with no such candidate merges onto the nearest attached cell within
   the radius, and is counted as merged. With none either, it is rejected: it
   keeps its raw position in the snapped map, so a grossly wrong map stays
   visible to Eq. 4, and it is counted;
5. a talweg cell no mapped cell moved onto is never added. A gap in the map is
   therefore not bridged: the reach above it attaches one cell lower, and the
   displacement says so.

Mapped cells outside the catchment are not scored by the criterion and are
kept as they are.

It lives in ``core`` for the reason :mod:`hydromodpy.core.stream_geometry`
does: the criterion scores the snapped map and the results layer redraws it,
and neither may import the other.
"""

from __future__ import annotations

import heapq
import math
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.topographic_distance import (
    DownslopeMetric,
    downslope_distance_to_mask,
    mean_downslope_distance,
)

SnapMode = Literal["off", "diagnose", "apply"]
"""``off`` computes nothing, ``diagnose`` computes and publishes, ``apply`` scores the snap."""

SNAP_MODE_CODE: dict[str, float] = {"off": 0.0, "diagnose": 1.0, "apply": 2.0}
"""The number a trial publishes as ``snap_mode``, since components are floats."""

SNAP_UNMAPPED = 0
SNAP_UNCHANGED = 1
SNAP_MOVED = 2
SNAP_MERGED = 3
SNAP_REJECTED = 4

SNAP_STATUS_LABELS: dict[int, str] = {
    SNAP_UNMAPPED: "unmapped",
    SNAP_UNCHANGED: "unchanged",
    SNAP_MOVED: "moved",
    SNAP_MERGED: "merged",
    SNAP_REJECTED: "rejected",
}
"""The name of each per-cell status, as the stored table spells it."""

_CELL_LENGTH = re.compile(r"^([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*(cells?)$")

# A radius of exactly two cells has to reach the cells two centres away,
# whatever the rounding of the centres.
_RADIUS_SLACK = 1.0e-9


def normalise_snap_length(value: Any) -> str:
    """Return a snap length in the one form it is stored in.

    ``"2 cells"`` and ``"1 cell"`` count cells of ``h_obs``. Any length Pint
    reads (``"200 m"``, ``"0.2 km"``) becomes metres, as does a bare number.
    ``normalise(normalise(x)) == normalise(x)``, so a sealed run reads back
    what it wrote.
    """
    if isinstance(value, bool):
        raise ValueError(f"a snap length is a length or a number of cells, got {value!r}.")
    if isinstance(value, int | float):
        metres = float(value)
    else:
        token = str(value).strip().lower()
        cells = _CELL_LENGTH.match(token)
        if cells is not None:
            count = float(cells.group(1))
            if count <= 0.0:
                raise ValueError(f"a snap length must be positive, got {value!r}.")
            return f"{count:g} cell" if count == 1.0 else f"{count:g} cells"
        from hydromodpy.core.units import UREG

        try:
            quantity = UREG(token)
            if not hasattr(quantity, "magnitude"):
                metres = float(quantity)
            elif quantity.dimensionless:
                metres = float(quantity.magnitude)
            else:
                metres = float(quantity.to("m").magnitude)
        except Exception as exc:  # Pint raises its own types; the config reads ValueError.
            raise ValueError(
                f"a snap length is a length ('200 m') or a number of cells ('2 cells'), "
                f"got {value!r}."
            ) from exc
    if not math.isfinite(metres) or metres <= 0.0:
        raise ValueError(f"a snap length must be positive, got {value!r}.")
    return f"{metres!r} m"


def snap_length_m(value: str, h_obs_m: float) -> float:
    """Return a normalised snap length in metres, a cell being ``h_obs_m``."""
    token = normalise_snap_length(value)
    count, unit = token.split(" ", 1)
    if unit.startswith("cell"):
        return float(count) * float(h_obs_m)
    return float(count)


class SnapStreamsConfig(HydroModelBase):
    """Snap the mapped stream network onto the talwegs of the criterion graph.

    Off by default. ``diagnose`` computes the snapped map, its indices and the
    floor ``F`` and publishes them, while the criterion still scores the raw
    map. ``apply`` scores the snapped map, and Eq. 4 then also bounds the
    displacement and the rejected share.
    """

    mode: Annotated[SnapMode, Profile.USER] = Field(
        default="off",
        description=(
            "'off' computes nothing. 'diagnose' snaps the mapped network, publishes the "
            "displacement, the rejected cells, the length change and the floor F, and "
            "scores the raw map. 'apply' scores the snapped map; Eq. 4 then also asks the "
            "p90 displacement and the rejected share to stay within their bounds."
        ),
    )
    radius: Annotated[str, Profile.USER] = Field(
        default="2 cells",
        description=(
            "How far a mapped cell may move. A length ('200 m') or a number of cells "
            "('2 cells'), a cell being h_obs, the median distance between neighbouring "
            "cell centres over the mapped cells of the catchment. Two cells is the "
            "outlet snapping distance of the paper."
        ),
    )
    max_displacement_p90: Annotated[str, Profile.USER] = Field(
        default="1 cell",
        description=(
            "Bound on the 90th percentile of the displacement, read by Eq. 4 in 'apply' "
            "mode. A length or a number of cells of h_obs. Keep it under the radius: a "
            "bound equal to the radius never fires."
        ),
    )
    max_rejected_share: Annotated[float, Profile.USER] = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description=(
            "Bound on the share of mapped cells of the catchment the snap could not "
            "place, read by Eq. 4 in 'apply' mode."
        ),
    )

    @field_validator("radius", "max_displacement_p90", mode="before")
    @classmethod
    def _normalise_length(cls, value: Any) -> str:
        return normalise_snap_length(value)

    @property
    def enabled(self) -> bool:
        """Return True when the snap is computed at all."""
        return self.mode != "off"

    def radius_m(self, h_obs_m: float) -> float:
        """Return the search radius in metres."""
        return snap_length_m(self.radius, h_obs_m)

    def displacement_bound_m(self, h_obs_m: float) -> float:
        """Return the Eq. 4 bound on the p90 displacement, in metres."""
        return snap_length_m(self.max_displacement_p90, h_obs_m)


SNAP_STREAMS_OFF = SnapStreamsConfig()
"""The default: no snap."""


@dataclass(frozen=True, slots=True)
class StreamSnap:
    """The snapped map, per cell, and the indices it publishes.

    ``raw`` is the mapped network the snap read, restricted to the catchment.
    ``snapped`` is the snapped map on the whole mesh: the cells moved onto,
    the rejected cells at their raw position, and the mapped cells outside the
    catchment as they were. ``target`` holds, for each raw cell, the cell it
    moved onto, and ``-1`` elsewhere or when it was rejected.
    """

    mode: SnapMode
    radius_m: float
    displacement_bound_m: float
    rejected_share_max: float
    h_obs_m: float
    raw: np.ndarray
    snapped: np.ndarray
    target: np.ndarray
    status: np.ndarray
    displacement_m: np.ndarray
    accumulation_percentile: np.ndarray
    raw_length_m: float
    snapped_length_m: float
    connected_share: float
    floor_m: float = float("nan")

    def _share(self, code: int) -> float:
        n_raw = int(self.raw.sum())
        return float(np.count_nonzero(self.status == code) / n_raw) if n_raw else float("nan")

    def _placed_percentile(self, q: float) -> float:
        placed = self.displacement_m[self.raw & np.isfinite(self.displacement_m)]
        return float(np.percentile(placed, q)) if placed.size else float("nan")

    @property
    def displacement_p50_m(self) -> float:
        """Median displacement over the placed mapped cells, in metres."""
        return self._placed_percentile(50.0)

    @property
    def displacement_p90_m(self) -> float:
        """90th percentile of the displacement over the placed mapped cells, in metres."""
        return self._placed_percentile(90.0)

    @property
    def rejected_share(self) -> float:
        """Share of the mapped cells of the catchment the snap could not place."""
        return self._share(SNAP_REJECTED)

    @property
    def length_ratio(self) -> float:
        """Length of the snapped map over the length of the raw one, in the catchment."""
        if self.raw_length_m <= 0.0:
            return float("nan")
        return float(self.snapped_length_m / self.raw_length_m)

    @property
    def within_bounds(self) -> bool:
        """Return True when the displacement and the rejected share pass Eq. 4 bounds."""
        p90 = self.displacement_p90_m
        rejected = self.rejected_share
        return (
            math.isfinite(p90)
            and p90 <= self.displacement_bound_m
            and math.isfinite(rejected)
            and rejected <= self.rejected_share_max
        )

    @property
    def indices(self) -> dict[str, float]:
        """The numbers a trial publishes, under the names it publishes them."""
        placed = self.raw & (self.target >= 0)
        percentile = self.accumulation_percentile[placed]
        percentile = percentile[np.isfinite(percentile)]
        return {
            "snap_mode": SNAP_MODE_CODE[self.mode],
            "snap_radius_m": float(self.radius_m),
            "snap_displacement_p50_m": self.displacement_p50_m,
            "snap_displacement_p90_m": self.displacement_p90_m,
            "snap_displacement_bound_m": float(self.displacement_bound_m),
            "snap_rejected_share": self.rejected_share,
            "snap_rejected_share_max": float(self.rejected_share_max),
            "snap_moved_share": self._share(SNAP_MOVED),
            "snap_merged_share": self._share(SNAP_MERGED),
            "snap_length_ratio": self.length_ratio,
            "snap_connected_share": float(self.connected_share),
            "snap_accumulation_percentile_p50": (
                float(np.median(percentile)) if percentile.size else float("nan")
            ),
            "snap_n_cells_raw": float(int(self.raw.sum())),
            "snap_floor_m": float(self.floor_m),
        }


def _elevation_rank(metric: DownslopeMetric) -> np.ndarray:
    """Return a rank that grows downstream: the position in descending elevation."""
    order = np.asarray(metric.graph.order, dtype=int)
    rank = np.full(metric.graph.active.size, -1, dtype=int)
    rank[order] = np.arange(order.size)
    return rank


def _pieces(mask: np.ndarray, adjacency: list[set[int]]) -> list[list[int]]:
    """Return the connected pieces of ``mask`` on ``adjacency``."""
    seen = np.zeros(mask.size, dtype=bool)
    pieces: list[list[int]] = []
    for start in np.flatnonzero(mask).tolist():
        if seen[start]:
            continue
        seen[start] = True
        piece = [start]
        stack = [start]
        while stack:
            cell = stack.pop()
            for near in adjacency[cell]:
                if mask[near] and not seen[near]:
                    seen[near] = True
                    piece.append(near)
                    stack.append(near)
        pieces.append(piece)
    return pieces


def _network_length_m(
    mask: np.ndarray, adjacency: list[set[int]], centres: np.ndarray, isolated_m: float
) -> float:
    """Return the length of a one-cell-wide network drawn on cells.

    Each cell counts the distance to its nearest neighbour inside the mask, so
    a chain of ``n`` cells measures ``n`` steps whatever its direction, and the
    raw and snapped maps are measured by one rule. An isolated cell counts
    ``isolated_m``.
    """
    total = 0.0
    for cell in np.flatnonzero(mask).tolist():
        near = [other for other in adjacency[cell] if mask[other]]
        if not near:
            total += float(isolated_m)
            continue
        offset = centres[near] - centres[cell]
        total += float(np.min(np.hypot(offset[:, 0], offset[:, 1])))
    return total


def _connected_share(metric: DownslopeMetric, network: np.ndarray, anchors: np.ndarray) -> float:
    """Share of ``network`` that descends to an anchor through ``network`` only."""
    receivers = metric.graph.downstream
    inside = network | anchors
    connected = np.zeros(network.size, dtype=bool)
    ascending = np.asarray(metric.graph.order, dtype=int)[::-1]
    for cell in ascending[inside[ascending]].tolist():
        if anchors[cell]:
            connected[cell] = True
            continue
        receiver = int(receivers[cell])
        connected[cell] = receiver >= 0 and inside[receiver] and connected[receiver]
    return float(np.mean(connected[network])) if network.any() else float("nan")


def snap_observed_network(
    *,
    metric: DownslopeMetric,
    observed: np.ndarray,
    outlet: int,
    catchment: np.ndarray,
    cell_area_m2: np.ndarray,
    adjacency: list[set[int]],
    h_obs_m: float,
    settings: SnapStreamsConfig,
    water_bodies: np.ndarray | None = None,
) -> StreamSnap:
    """Snap the mapped cells of the catchment onto the talwegs of ``metric``.

    ``adjacency`` is the neighbour graph the metric descends, which groups the
    mapped cells into pieces. ``cell_area_m2`` weighs the accumulation into a
    drained area. ``water_bodies`` are attached from the start, like the
    outlet. The module docstring states the rule.
    """
    from scipy.spatial import cKDTree

    if not settings.enabled:
        raise ValueError("the snap is off: there is nothing to compute.")
    graph = metric.graph
    active = np.asarray(graph.active, dtype=bool)
    n_cells = active.size
    receivers = np.asarray(graph.downstream, dtype=int)
    observed_mask = np.asarray(observed, dtype=bool).reshape(-1) & active
    inside = np.asarray(catchment, dtype=bool).reshape(-1) & active
    raw = observed_mask & inside
    radius = settings.radius_m(h_obs_m)

    areas = np.asarray(cell_area_m2, dtype=float).reshape(-1)
    weights = np.where(np.isfinite(areas) & (areas > 0.0), areas, 0.0)
    accumulated = accumulate_on_downhill_graph(graph, weights)
    accumulated = np.where(np.isfinite(accumulated), accumulated, 0.0)
    rank = _elevation_rank(metric)
    centres = np.asarray(metric.centroids, dtype=float)

    pool = np.flatnonzero(inside & np.isfinite(centres).all(axis=1))
    tree = cKDTree(centres[pool])

    anchors = np.zeros(n_cells, dtype=bool)
    anchors[int(outlet)] = True
    if water_bodies is not None:
        anchors |= np.asarray(water_bodies, dtype=bool).reshape(-1) & inside
    attached = anchors.copy()
    claimed = np.zeros(n_cells, dtype=bool)
    target = np.full(n_cells, -1, dtype=int)
    status = np.full(n_cells, SNAP_UNMAPPED, dtype=np.int8)

    def choose(cell: int) -> tuple[int, int]:
        found = pool[tree.query_ball_point(centres[cell], r=radius * (1.0 + _RADIUS_SLACK))]
        if found.size == 0:
            return -1, SNAP_REJECTED
        offset = centres[found] - centres[cell]
        distance = np.hypot(offset[:, 0], offset[:, 1])
        free = ~claimed[found]
        receiver = np.clip(receivers[found], 0, n_cells - 1)
        has_receiver = receivers[found] >= 0
        # Any attached cell, not only the cells of the mapped neighbours: on a
        # tortuous talweg the map and the chain drift by a cell or two, and a
        # cell bound to its neighbours' chain cannot catch up and is rejected
        # with everything upstream of it. Measured on noisy synthetic
        # catchments, binding to the neighbours or preferring a merge doubled
        # to tripled the rejected share of a map shifted by one column.
        frontier = free & ((has_receiver & attached[receiver]) | anchors[found])
        if frontier.any():
            index = np.flatnonzero(frontier)
            # Most accumulated first, then nearest, then the lowest.
            best = index[
                np.lexsort((-rank[found[index]], distance[index], -accumulated[found[index]]))[0]
            ]
            chosen = int(found[best])
            return chosen, SNAP_UNCHANGED if chosen == cell else SNAP_MOVED
        taken = np.flatnonzero(claimed[found])
        if taken.size:
            best = taken[np.lexsort((-accumulated[found[taken]], distance[taken]))[0]]
            return int(found[best]), SNAP_MERGED
        return -1, SNAP_REJECTED

    queued = np.zeros(n_cells, dtype=bool)
    heap: list[tuple[float, int, int]] = []
    for piece in _pieces(raw, adjacency):
        members = np.asarray(piece, dtype=int)
        # The lowest cell, not the most accumulated one: a map shifted onto a
        # hillslope carries the noise of the hillslope in its accumulation,
        # while its lowest cell still sits at its downstream end.
        root = int(members[np.argmax(rank[members])])
        queued[root] = True
        heapq.heappush(heap, (-float(accumulated[root]), -int(rank[root]), root))
    while heap:
        _, _, cell = heapq.heappop(heap)
        chosen, outcome = choose(cell)
        status[cell] = outcome
        if chosen >= 0:
            target[cell] = chosen
            if outcome != SNAP_MERGED:
                claimed[chosen] = True
                attached[chosen] = True
        for near in adjacency[cell]:
            if raw[near] and not queued[near]:
                queued[near] = True
                heapq.heappush(heap, (-float(accumulated[near]), -int(rank[near]), near))

    placed = raw & (target >= 0)
    snapped = np.zeros(n_cells, dtype=bool)
    snapped[target[placed]] = True
    snapped |= raw & (status == SNAP_REJECTED)
    snapped |= observed_mask & ~inside

    displacement = np.full(n_cells, np.nan)
    offset = centres[target[placed]] - centres[placed]
    displacement[placed] = np.hypot(offset[:, 0], offset[:, 1])

    percentile = np.full(n_cells, np.nan)
    ranked = np.sort(accumulated[inside])
    if ranked.size:
        percentile[placed] = (
            100.0 * np.searchsorted(ranked, accumulated[target[placed]], side="right") / ranked.size
        )

    snapped_inside = snapped & inside
    return StreamSnap(
        mode=settings.mode,
        radius_m=float(radius),
        displacement_bound_m=float(settings.displacement_bound_m(h_obs_m)),
        rejected_share_max=float(settings.max_rejected_share),
        h_obs_m=float(h_obs_m),
        raw=raw,
        snapped=snapped,
        target=target,
        status=status,
        displacement_m=displacement,
        accumulation_percentile=percentile,
        raw_length_m=_network_length_m(raw, adjacency, centres, h_obs_m),
        snapped_length_m=_network_length_m(snapped_inside, adjacency, centres, h_obs_m),
        connected_share=_connected_share(metric, snapped_inside, anchors),
    )


def representation_floor_m(
    *,
    metric: DownslopeMetric,
    raw: np.ndarray,
    snapped: np.ndarray,
    outlet: int,
    keep: np.ndarray,
    saturation_cap_m: float,
    water_bodies: np.ndarray | None = None,
    weights: np.ndarray | None = None,
) -> float:
    """Return ``F``, the ``Doptim`` of the snapped map scored against the raw one.

    It is the ``Doptim`` a model reproducing the talwegs of the snapped map
    exactly would reach, read with the criterion metric: the snapped map takes
    the place of the simulated network. ``D_so`` descends from the snapped
    cells to the raw map, water bodies and sealed outlet included; ``D_os``
    descends from the raw cells to the snapped map. Both average over
    ``keep`` and cap an unreachable cell at ``saturation_cap_m``.

    ``weights`` is the weighting the scored ``Doptim`` uses: None for one
    weight per cell, the cell areas for the ``"area"`` weighting. ``F`` bounds
    that ``Doptim`` only when both are averaged the same way.
    """
    raw_mask = np.asarray(raw, dtype=bool).reshape(-1)
    snapped_mask = np.asarray(snapped, dtype=bool).reshape(-1)
    support = np.asarray(keep, dtype=bool).reshape(-1)
    target = raw_mask.copy()
    if water_bodies is not None:
        target |= np.asarray(water_bodies, dtype=bool).reshape(-1)
    target[int(outlet)] = True
    d_so = mean_downslope_distance(
        downslope_distance_to_mask(metric, target),
        snapped_mask & support,
        weights=weights,
        saturation_cap_m=saturation_cap_m,
    ).mean_m
    d_os = mean_downslope_distance(
        downslope_distance_to_mask(metric, snapped_mask),
        raw_mask & support,
        weights=weights,
        saturation_cap_m=saturation_cap_m,
    ).mean_m
    return 0.5 * float(d_so + d_os)


__all__ = (
    "SNAP_MERGED",
    "SNAP_MODE_CODE",
    "SNAP_MOVED",
    "SNAP_REJECTED",
    "SNAP_STATUS_LABELS",
    "SNAP_STREAMS_OFF",
    "SNAP_UNCHANGED",
    "SNAP_UNMAPPED",
    "SnapMode",
    "SnapStreamsConfig",
    "StreamSnap",
    "normalise_snap_length",
    "representation_floor_m",
    "snap_length_m",
    "snap_observed_network",
)

"""The lake shores a generated Voronoi mesh can follow, at its local cell size.

The generated ``voronoi`` engine lays one mirror pair of generators on each
segment of a face line, about one cell long. Where two stretches of shore come
closer than about a cell (an arm narrower than a cell, a spit, the sill between
two lakes), the pairs of one stretch fall inside the circles of the other and
yield: the shore is followed in part, its faces enclose no region, and the lake
falls back on the overlap rule.

The planner gives the engine the shore it can follow. Each lake is opened,
closed and opened again by ``LAKE_SHORE_SHARE`` times the largest cell size
along its shore, and its parts are drawn apart: arms, necks and gaps narrower
than twice that radius go. Only the changes larger than a rounded corner are
kept; elsewhere the lake keeps its own outline. Near a barrier line laid on the
shore the outline is the lake's own, so the barrier still runs on the ring. A
later lake closer to an earlier one than twice the radius at their nearest
points gives up the strip next to it. The lake polygons of the flow model are
not changed: only the rings the mesh follows. A cell of an arm left out still
joins its lake when the lake covers most of it
(``solver/modflow6/builders/_lake_geometry.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from hydromodpy.spatial.mesh.model.geometry import polygon_rings

__all__ = ["LAKE_SHORE_SHARE", "SIGNIFICANT_SHARE", "FollowedShores", "followed_lake_shores"]

LAKE_SHORE_SHARE = 0.6
"""Radius of the opening and closing of a lake, as a share of its largest shore cell.

A vertex circle reaches 0.55 segment and a mirror pair sits 0.23 segment off
its line: the opposite shore must stay more than about 0.8 segment away, and
around a lobe of that radius a segment turns by less than 100 degrees. On the
Cheze reservoir (cells of 80 to 100 m on a DEM of 75 m) the shores of both
lakes close from 0.5 to 0.7; 0.6 keeps a margin on both sides.
"""

SIGNIFICANT_SHARE = 0.5
"""A change of the outline counts above this share of the squared radius.

A right corner rounded by the radius moves ``(1 - pi / 4) = 0.21`` of it, a
corner of 60 degrees ``0.69``: the engine keeps the pairs of the first and
merges those of the second.
"""

_SIMPLIFY_SHARE = 0.1
"""Tolerance of the outline simplification before the buffers, as a share of the radius."""

_QUAD_SEGS = 4
"""Segments per quarter circle of the buffers: the resampling cuts the arcs anyway."""

_SAMPLE_SHARE = 0.25
"""Spacing of the size samples along a shore, as a share of the finest size."""


@dataclass(frozen=True)
class FollowedShores:
    """The lake outlines the mesh follows, one per lake, and what the change moved.

    ``polygons`` keeps the order of the lakes. ``radius_m``, ``left_out_m2`` and
    ``taken_in_m2`` give, per lake, the radius of the smoothing, the area of the
    lake left out of the outline and the area of land taken in.
    """

    polygons: tuple[BaseGeometry, ...]
    radius_m: tuple[float, ...]
    left_out_m2: tuple[float, ...]
    taken_in_m2: tuple[float, ...]

    def notes(self) -> tuple[str, ...]:
        """One note per lake whose outline moved."""
        out = []
        for index, (radius, out_m2, in_m2) in enumerate(
            zip(self.radius_m, self.left_out_m2, self.taken_in_m2, strict=True)
        ):
            if out_m2 <= 0.0 and in_m2 <= 0.0:
                continue
            out.append(
                f"lakes: the faces follow lake {index} smoothed at {radius:.1f} m, the "
                f"cell scale: {out_m2:.0f} m2 of arms narrower than {2.0 * radius:.0f} m "
                f"left out, {in_m2:.0f} m2 of land as narrow taken in; a cell the lake "
                "covers for most of its area stays a lake cell"
            )
        return tuple(out)


def followed_lake_shores(
    lakes: Sequence[Polygon],
    size_at: Callable[[np.ndarray], np.ndarray],
    *,
    barriers: Sequence[LineString] = (),
    rivers: Sequence[LineString] = (),
    finest: float,
) -> FollowedShores:
    """Return the outlines of *lakes* that a generated Voronoi mesh follows.

    ``size_at`` maps points ``(k, 2)`` to the local cell size [m]; *finest* is
    the finest size of the field [m], the sample spacing along the shores.
    Land a river runs on stays land, a radius wide on each side: its reaches
    need river cells there. A lake whose smoothed outline vanishes keeps its own.
    """
    step = _SAMPLE_SHARE * float(finest)
    radii = [LAKE_SHORE_SHARE * _shore_size(lake, size_at, step) for lake in lakes]
    on_land = shapely.union_all(list(rivers)) if rivers else None
    shaped = [
        _smoothed(lake, radius, barriers, _off_the_lake(on_land, lake))
        for lake, radius in zip(lakes, radii, strict=True)
    ]
    for later in range(len(shaped)):
        for earlier in range(later):
            shaped[later] = _apart(shaped[later], shaped[earlier], size_at, radius=radii[later])
    kept = [
        smooth if not smooth.is_empty else lake for lake, smooth in zip(lakes, shaped, strict=True)
    ]
    return FollowedShores(
        polygons=tuple(kept),
        radius_m=tuple(radii),
        left_out_m2=tuple(
            float(lake.difference(smooth).area) for lake, smooth in zip(lakes, kept, strict=True)
        ),
        taken_in_m2=tuple(
            float(smooth.difference(lake).area) for lake, smooth in zip(lakes, kept, strict=True)
        ),
    )


def _shore_size(lake: Polygon, size_at: Callable[[np.ndarray], np.ndarray], step: float) -> float:
    """The largest cell size [m] along the rings of *lake*: its longest shore segment."""
    samples = []
    for line in polygon_rings(lake):
        count = max(4, int(np.ceil(line.length / step)))
        along = np.linspace(0.0, line.length, count, endpoint=False)
        samples.append(shapely.get_coordinates(shapely.line_interpolate_point(line, along)))
    return float(np.max(size_at(np.vstack(samples))))


def _smoothed(
    lake: Polygon,
    radius: float,
    barriers: Sequence[LineString],
    rivers: BaseGeometry | None,
) -> BaseGeometry:
    """*lake* with no part, neck or gap narrower than ``2 radius``, its outline kept along barriers.

    The lake is opened, closed and opened again: arms go, narrow land is taken
    in, and a neck the closing drew between two lobes goes. The land along the
    *rivers* off the lake is given back. Two parts left closer than ``2 radius``
    are then drawn apart, the smaller giving way.
    """
    simple = lake.simplify(_SIMPLIFY_SHARE * radius, preserve_topology=True)
    shaped = _opened(_closed(_opened(simple, radius), radius), radius)
    if rivers is not None and not rivers.is_empty:
        corridor = rivers.buffer(radius, quad_segs=_QUAD_SEGS)
        shaped = _opened(shaped.difference(corridor), radius)
    shaped = _parts_apart(shaped, radius)
    kept = _with_barrier_outline(_changes_that_count(lake, shaped, radius), lake, radius, barriers)
    return _without_crumbs(kept, radius)


def _changes_that_count(lake: Polygon, shaped: BaseGeometry, radius: float) -> BaseGeometry:
    """*lake* with only the changes of *shaped* larger than ``SIGNIFICANT_SHARE radius**2``.

    A rounded right corner or the simplification of a pixel staircase moves
    less than that, and the engine follows it as it is; the lake keeps its own
    outline there. An arm, a spit, a neck or an acute corner moves more.
    """
    if shaped.is_empty:
        return shaped
    floor = SIGNIFICANT_SHARE * radius * radius
    left_out = [part for part in shapely.get_parts(lake.difference(shaped)) if part.area > floor]
    taken_in = [part for part in shapely.get_parts(shaped.difference(lake)) if part.area > floor]
    if not left_out and not taken_in:
        return lake
    kept = lake.difference(shapely.union_all(left_out)) if left_out else lake
    return _polygonal(kept.union(shapely.union_all(taken_in)) if taken_in else kept)


def _off_the_lake(rivers: BaseGeometry | None, lake: Polygon) -> BaseGeometry | None:
    """The parts of *rivers* that run outside *lake*, or None."""
    if rivers is None:
        return None
    outside = rivers.difference(lake)
    return None if outside.is_empty else outside


def _opened(geometry: BaseGeometry, radius: float) -> BaseGeometry:
    """The union of the discs of *radius* inside *geometry*."""
    eroded = geometry.buffer(-radius, quad_segs=_QUAD_SEGS)
    return _polygonal(eroded.buffer(radius, quad_segs=_QUAD_SEGS))


def _closed(geometry: BaseGeometry, radius: float) -> BaseGeometry:
    """*geometry* with every gap narrower than ``2 radius`` filled."""
    grown = geometry.buffer(radius, quad_segs=_QUAD_SEGS)
    return _polygonal(grown.buffer(-radius, quad_segs=_QUAD_SEGS))


def _parts_apart(geometry: BaseGeometry, radius: float) -> BaseGeometry:
    """The parts of *geometry* at least ``2 radius`` apart, the larger first."""
    gap = 2.0 * radius
    kept: list[BaseGeometry] = []
    for part in sorted(shapely.get_parts(geometry), key=lambda part: -part.area):
        for other in kept:
            if part.is_empty:
                break
            if part.distance(other) < gap:
                part = _opened(part.difference(other.buffer(gap, quad_segs=_QUAD_SEGS)), radius)
        kept.extend(p for p in shapely.get_parts(part) if not p.is_empty)
    return _polygonal(shapely.union_all(kept)) if kept else Polygon()


def _apart(
    later: BaseGeometry,
    earlier: BaseGeometry,
    size_at: Callable[[np.ndarray], np.ndarray],
    *,
    radius: float,
) -> BaseGeometry:
    """*later* less the strip closer to *earlier* than ``2 LAKE_SHORE_SHARE`` local cells."""
    if later.is_empty or earlier.is_empty:
        return later
    near = np.vstack([np.asarray(point.coords) for point in nearest_points(later, earlier)])
    gap = 2.0 * LAKE_SHORE_SHARE * float(np.max(size_at(near)))
    if later.distance(earlier) >= gap:
        return later
    cut = _opened(later.difference(earlier.buffer(gap, quad_segs=_QUAD_SEGS)), radius)
    return _without_crumbs(cut, radius)


def _with_barrier_outline(
    shaped: BaseGeometry, lake: Polygon, radius: float, barriers: Sequence[LineString]
) -> BaseGeometry:
    """*shaped* with the outline of *lake* put back within *radius* of each barrier stretch.

    A stretch is a part of a barrier line laid on the shore of *lake*. Across
    the band along it, flat at its ends, the outline is the lake's own, so the
    stretch stays on the ring the mesh follows.
    """
    if shaped.is_empty:
        return shaped
    stretches = [
        part
        for line in barriers
        for part in shapely.get_parts(shapely.line_merge(line.intersection(lake.boundary)))
        if isinstance(part, LineString) and part.length > 0.0
    ]
    if not stretches:
        return shaped
    band = shapely.union_all(
        [stretch.buffer(radius, cap_style="flat", quad_segs=_QUAD_SEGS) for stretch in stretches]
    )
    return _polygonal(shaped.difference(band).union(lake.intersection(band)))


def _without_crumbs(geometry: BaseGeometry, radius: float) -> BaseGeometry:
    """*geometry* without the parts and holes smaller than ``radius**2``.

    The overlays leave crumbs where two outlines meet: a hole of a few square
    meters, whose ring the mesh would follow in segments of a few meters.
    """
    floor = radius * radius
    parts = []
    for part in shapely.get_parts(geometry):
        if part.area < floor:
            continue
        holes = [ring for ring in part.interiors if Polygon(ring).area >= floor]
        parts.append(Polygon(part.exterior, holes))
    return _polygonal(shapely.union_all(parts)) if parts else Polygon()


def _polygonal(geometry: BaseGeometry) -> BaseGeometry:
    """The polygons of *geometry*: a Polygon, a MultiPolygon, or an empty Polygon."""
    parts = [part for part in shapely.get_parts(geometry) if isinstance(part, Polygon)]
    parts = [part for part in parts if not part.is_empty and part.area > 0.0]
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)

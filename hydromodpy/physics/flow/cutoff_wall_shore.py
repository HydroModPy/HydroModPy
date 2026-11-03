"""Lay a declared cutoff-wall trace on the lake shore it faces.

A dam cutoff wall must lie on the lake shore, so no cell sits between the
reservoir and the wall. The trace a user digitizes rarely does: it runs a few
meters downstream of the footprint, or across it. :func:`snap_wall_to_shore`
moves the part of the trace facing the lake onto the shore section it faces
and keeps the wings beyond the banks. Pure shapely, so it binds before the mesh
exists and the mesh refines around the snapped wall.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, split, substring

__all__ = ["SnappedWall", "snap_wall_to_shore"]

_STATIONS = 2000
"""Trace samples used to find the shore section the trace faces."""

_MIN_STEP_M = 0.05
"""Finest sample spacing along the trace [m]."""

_FACING_ANGLE_DEG = 45.0
"""A shore point faces the trace when reached within this angle of the trace normal.

Past a corner of the dam shore the outline turns away along a bank: the trace
still reaches it, but obliquely. Stopping the shore section there keeps the
wall from folding back along the bank before it joins the trace.
"""


@dataclass(frozen=True)
class SnappedWall:
    """A cutoff wall laid on the lake shore.

    ``line`` runs with the lake on its left: wing, joint to the shore, shore
    section, joint back to the trace, wing. ``shore`` is the shore section the
    wall follows (empty when the trace only touches a point of the shore).
    ``polygon`` is the lake footprint, cut along the trace when the trace
    crosses it. ``gap_m`` is the distance from the declared trace to the lake,
    and ``cut_area_m2`` the lake area dropped downstream of a crossing trace.
    """

    line: LineString
    shore: LineString
    polygon: BaseGeometry
    gap_m: float
    cut_area_m2: float


def snap_wall_to_shore(
    lake_polygon: BaseGeometry, trace: LineString, tolerance: float
) -> SnappedWall:
    """Move the part of *trace* facing the lake onto the shore it faces.

    The shore section is the part of the lake outline nearest to the trace
    points that face it: within *tolerance* [m], and reached within 45 degrees
    of the trace normal. Each end of that section is joined to its foot on the
    trace, and the trace beyond those feet is kept as the wings. A trace that
    crosses the lake first cuts the footprint along the trace; the largest
    piece stays the lake and the wall lies on the new shore. A trace farther
    than *tolerance* from the lake, one that faces no shore, or one that enters
    the lake without crossing it raises ``ValueError``.
    """
    parts = list(getattr(lake_polygon, "geoms", [lake_polygon]))
    nearest = int(np.argmin([part.distance(trace) for part in parts]))
    lake = parts[nearest]
    gap = float(lake.distance(trace))
    if gap > tolerance:
        raise ValueError(
            f"the trace stops {gap:.1f} m from the lake shore, farther than "
            f"snap_tolerance = {tolerance:g} m"
        )
    lake, cut_area = _cut_along_trace(lake, trace)
    parts[nearest] = lake
    polygon = parts[0] if len(parts) == 1 else MultiPolygon(parts)
    line, shore = _laid_on_shore(orient(lake, sign=1.0).exterior, trace, tolerance)
    return SnappedWall(line=line, shore=shore, polygon=polygon, gap_m=gap, cut_area_m2=cut_area)


def _cut_along_trace(lake: Polygon, trace: LineString) -> tuple[Polygon, float]:
    """The lake cut along the trace, its largest piece kept, and the area dropped."""
    inside = trace.intersection(lake).length - trace.intersection(lake.boundary).length
    if inside <= 1.0e-9 * max(trace.length, 1.0):
        return lake, 0.0
    pieces = sorted(split(lake, trace).geoms, key=lambda piece: piece.area, reverse=True)
    if len(pieces) < 2:
        raise ValueError("the trace enters the lake without crossing it; extend it past both banks")
    kept = pieces[0]
    return kept, float(sum(piece.area for piece in pieces[1:]))


def _laid_on_shore(
    ring: LineString, trace: LineString, tolerance: float
) -> tuple[LineString, LineString]:
    """The wall through the shore section the trace faces, and that section.

    *ring* runs counter-clockwise, so the lake lies on the left of its sections.
    """
    step = max(trace.length / _STATIONS, _MIN_STEP_M)
    closest = nearest_points(trace, ring)[0]
    touching = shapely.get_coordinates(trace.intersection(ring))
    samples = shapely.points(
        np.vstack(
            [shapely.get_coordinates(shapely.segmentize(trace, step)), closest.coords, touching]
        )
    )
    on_ring = shapely.line_locate_point(ring, samples)
    facing = _facing(trace, samples, ring, on_ring, tolerance)
    if not facing.any():
        raise ValueError(
            f"the trace faces no lake shore within snap_tolerance = {tolerance:g} m; "
            "it passes beside the lake instead of across its outlet"
        )
    start, end = _covering_arc(np.sort(on_ring[facing]), ring.length)
    first = ring.interpolate(start)
    last = ring.interpolate(end)
    shore = _ring_arc(ring, start, end)
    if trace.project(first) > trace.project(last):
        trace = trace.reverse()
    foot_first, foot_last = trace.project(first), trace.project(last)
    coords: list[tuple[float, float]] = []
    if foot_first > 0.0:
        coords.extend(substring(trace, 0.0, foot_first).coords)
    coords.append(first.coords[0])
    if not shore.is_empty:
        coords.extend(shore.coords)
    coords.append(last.coords[0])
    if foot_last < trace.length:
        coords.extend(substring(trace, foot_last, trace.length).coords)
    return LineString(_without_repeats(coords)), shore


def _facing(
    trace: LineString,
    samples: np.ndarray,
    ring: LineString,
    on_ring: np.ndarray,
    tolerance: float,
) -> np.ndarray:
    """Whether each trace sample faces its nearest shore point.

    It does when that point lies within *tolerance* and within the facing angle
    of the trace normal at the sample. A sample on the shore always faces it.
    """
    xy = shapely.get_coordinates(samples)
    offset = shapely.get_coordinates(shapely.line_interpolate_point(ring, on_ring)) - xy
    reach = np.hypot(*offset.T)
    along = shapely.line_locate_point(trace, samples)
    step = 1.0e-6 * max(trace.length, 1.0)
    before = shapely.line_interpolate_point(trace, np.maximum(along - step, 0.0))
    after = shapely.line_interpolate_point(trace, np.minimum(along + step, trace.length))
    tangent = shapely.get_coordinates(after) - shapely.get_coordinates(before)
    tangent /= np.hypot(*tangent.T)[:, None]
    oblique = np.abs(np.sum(offset * tangent, axis=1))
    square = oblique <= np.sin(np.radians(_FACING_ANGLE_DEG)) * reach + 1.0e-9
    return (reach <= tolerance + 1.0e-9) & square


def _covering_arc(stations: np.ndarray, length: float) -> tuple[float, float]:
    """Start and end of the shortest ring arc that holds every station.

    The arc runs in the ring direction and may wrap past the ring origin.
    """
    if stations.size == 1:
        return float(stations[0]), float(stations[0])
    gaps = np.diff(np.append(stations, stations[0] + length))
    widest = int(np.argmax(gaps))
    return float(stations[(widest + 1) % stations.size]), float(stations[widest])


def _ring_arc(ring: LineString, start: float, end: float) -> LineString:
    """The ring from *start* to *end* in its direction; empty when they meet."""
    if abs(end - start) <= 1.0e-9 * max(ring.length, 1.0):
        return LineString()
    if start < end:
        return substring(ring, start, end)
    head = list(substring(ring, start, ring.length).coords)
    tail = list(substring(ring, 0.0, end).coords)
    return LineString(_without_repeats(head + tail))


def _without_repeats(coords: list) -> list[tuple[float, float]]:
    """The coordinates without consecutive duplicates."""
    points = np.asarray(coords, dtype=float)[:, :2]
    keep = np.ones(len(points), dtype=bool)
    keep[1:] = np.hypot(*np.diff(points, axis=0).T) > 1.0e-9
    return [tuple(point) for point in points[keep]]

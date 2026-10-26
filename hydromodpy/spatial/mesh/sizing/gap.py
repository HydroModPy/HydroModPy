"""The size terms that follow the gap between the face lines and the domain outline.

Two face lines a few cells apart, or the two shores of a narrow lake arm,
leave no room for the cells their faces need. Each line is sampled every half
pixel. At a sample ``p`` the gap ``e`` is the distance to the nearest point
``q`` of another line, or of the same line far enough along it, when the
chord ``pq`` lies in the domain. The chord is sized ``e / cells_across``,
never finer than the pixel, and the size grows away from it at ``max_slope``
like every other term. The sizes are rounded down to a few levels, one term
per level: the distances are one transform per level, never one per line.
Rivers are cell chains and stay out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.spatial.mesh.sizing.size_field import SizeTerm

__all__ = ["GAP_DETOUR", "GAP_LEVEL_RATIO", "gap_terms"]

GAP_DETOUR = 2.0
"""A point of the same line, or of a line it touches, is across a gap only when
the way along the lines is more than this many times the straight distance.
A corner sharper than 53 degrees qualifies, a right angle does not."""

GAP_LEVEL_RATIO = 2.0**0.25
"""Ratio of two size levels. A gap size is rounded down to its level, so a gap
holds between ``cells_across`` and 1.19 times as many cells."""

_SIMPLIFY_SHARE = 0.25
"""The lines are simplified at this share of the pixel first: a pixel staircase
holds many short segments, and a gap is only read to the pixel."""

_BLOCK = 20_000
"""Samples per tree query, which bounds the memory of the pairs."""


def gap_terms(
    lines: Sequence[LineString],
    *,
    domain: Polygon,
    h0: float,
    pixel: float,
    cells_across: float,
    touch: float,
) -> list[SizeTerm]:
    """The size terms of the gaps between *lines* and the rings of *domain*.

    A gap of ``e`` sizes its chord ``max(e / cells_across, pixel)``. Only the
    gaps finer than ``cells_across * h0`` refine anything. Two lines closer
    than *touch* [m] touch there, and the way between two of their points
    goes through the place they touch.
    """
    rings = [LineString(domain.exterior.coords)]
    rings.extend(LineString(ring.coords) for ring in domain.interiors)
    simple = shapely.simplify(np.asarray([*lines, *rings], dtype=object), _SIMPLIFY_SHARE * pixel)
    kept = _distinct([line for line in simple if line.length > 0.0], touch)
    if not kept:
        return []
    radius = cells_across * h0
    segments = _Segments(kept)
    tree = shapely.STRtree(segments.geoms)
    samples, sample_line, sample_arc = _samples(kept, 0.5 * pixel)
    touching = _Touching(kept, touch)
    room = domain.buffer(touch)
    shapely.prepare(room)
    gap = np.full(len(samples), np.inf)
    far = np.zeros((len(samples), 2))
    for start in range(0, len(samples), _BLOCK):
        block = slice(start, start + _BLOCK)
        pairs = tree.query(shapely.points(samples[block]), predicate="dwithin", distance=radius)
        index = pairs[0] + start
        pair = _Pairs(samples[index], sample_line[index], sample_arc[index], pairs[1], segments)
        where = _across(pair, index, touching, room)
        if where.size == 0:
            continue
        index, distance, nearest = index[where], pair.distance[where], pair.nearest[where]
        order = np.lexsort((distance, index))
        chosen = order[np.unique(index[order], return_index=True)[1]]
        gap[index[chosen]] = distance[chosen]
        far[index[chosen]] = nearest[chosen]
    sizes = np.maximum(gap / cells_across, pixel)
    refined = np.flatnonzero(sizes < h0)
    if refined.size == 0:
        return []
    levels = np.floor(np.log(sizes[refined] / pixel) / math.log(GAP_LEVEL_RATIO) + 1.0e-9)
    terms = []
    for level in np.unique(levels):
        chosen = refined[levels == level]
        chords = shapely.linestrings(np.stack([samples[chosen], far[chosen]], axis=1))
        terms.append(
            SizeTerm(
                name=f"gap:{int(level)}",
                region=shapely.multilinestrings(chords),
                size_m=float(pixel * GAP_LEVEL_RATIO**level),
                ramp_m=0.0,
            )
        )
    return terms


def _distinct(lines: list[LineString], touch: float) -> list[LineString]:
    """*lines* without one that lies within *touch* of a line kept before it.

    A catchment boundary that is the domain outline is one line, not two
    lines that touch all along.
    """
    kept: list[LineString] = []
    for line in lines:
        if not any(
            other.envelope.buffer(touch).covers(line.envelope) and other.buffer(touch).covers(line)
            for other in kept
        ):
            kept.append(line)
    return kept


class _Segments:
    """Every segment of the lines, with its line and the arc length at its start."""

    def __init__(self, lines: Sequence[LineString]) -> None:
        starts, ends, owner, arc = [], [], [], []
        self.length = np.array([line.length for line in lines])
        self.closed = np.array([line.is_closed for line in lines])
        for index, line in enumerate(lines):
            coords = np.asarray(line.coords, dtype=float)[:, :2]
            steps = np.hypot(*np.diff(coords, axis=0).T)
            keep = steps > 0.0
            starts.append(coords[:-1][keep])
            ends.append(coords[1:][keep])
            owner.append(np.full(int(keep.sum()), index))
            arc.append(np.concatenate([[0.0], np.cumsum(steps)[:-1]])[keep])
        self.start = np.concatenate(starts)
        self.end = np.concatenate(ends)
        self.line = np.concatenate(owner)
        self.arc = np.concatenate(arc)
        self.geoms = shapely.linestrings(np.stack([self.start, self.end], axis=1))


class _Touching:
    """Where two lines touch, computed once per pair of lines."""

    def __init__(self, lines: Sequence[LineString], touch: float) -> None:
        self.lines = lines
        self.touch = touch
        self._places: dict[tuple[int, int], BaseGeometry | None] = {}

    def place(self, first: int, second: int) -> BaseGeometry | None:
        """The stretch of *first* within the tolerance of *second*, or None."""
        key = (min(first, second), max(first, second))
        if key not in self._places:
            one, two = (self.lines[index] for index in key)
            place = None
            if one.distance(two) <= self.touch:
                place = one.intersection(two.buffer(self.touch))
                place = None if place.is_empty else place
            self._places[key] = place
        return self._places[key]


def _samples(lines: Sequence[LineString], step: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points every *step* at most along each line, with their line and arc length."""
    points, owner, arcs = [], [], []
    for index, line in enumerate(lines):
        count = max(math.ceil(line.length / step), 1)
        arc = np.linspace(0.0, line.length, count + 1)
        if line.is_closed:
            arc = arc[:-1]
        points.append(shapely.get_coordinates(shapely.line_interpolate_point(line, arc)))
        owner.append(np.full(len(arc), index))
        arcs.append(arc)
    return np.concatenate(points), np.concatenate(owner), np.concatenate(arcs)


class _Pairs:
    """Sample and segment pairs: the nearest point of the segment, its distance, and the way."""

    def __init__(
        self,
        points: np.ndarray,
        line: np.ndarray,
        arc: np.ndarray,
        segment: np.ndarray,
        segments: _Segments,
    ) -> None:
        start = segments.start[segment]
        step = segments.end[segment] - start
        span = np.einsum("ij,ij->i", step, step)
        t = np.clip(np.einsum("ij,ij->i", points - start, step) / span, 0.0, 1.0)
        self.points = points
        self.line = line
        self.other = segments.line[segment]
        self.nearest = start + t[:, None] * step
        self.distance = np.hypot(*(self.nearest - points).T)
        along = np.abs(segments.arc[segment] + t * np.sqrt(span) - arc)
        total = segments.length[line]
        self.along = np.where(segments.closed[line], np.minimum(along, total - along), along)


def _across(
    pairs: _Pairs, sample: np.ndarray, touching: _Touching, room: BaseGeometry
) -> np.ndarray:
    """The positions of the pairs that span a gap.

    A pair spans a gap when it is farther apart than the touch tolerance, the
    way along the lines is more than :data:`GAP_DETOUR` times the distance,
    and the chord lies in *room*, the domain grown by the touch tolerance.
    The way through the place two lines touch is only measured for a pair
    nearer than the best gap its sample already has.
    """
    apart = pairs.distance > touching.touch
    same = pairs.line == pairs.other
    touch = np.zeros(len(same), dtype=bool)
    links = np.stack([pairs.line, pairs.other], axis=1)
    for first, second in np.unique(links[apart & ~same], axis=0):
        if touching.place(int(first), int(second)) is not None:
            touch |= (links[:, 0] == first) & (links[:, 1] == second)
    plain = apart & ((same & (pairs.along > GAP_DETOUR * pairs.distance)) | (~same & ~touch))
    found = _in_room(pairs, np.flatnonzero(plain), room)
    best = np.full(sample.max() + 1, np.inf)
    np.minimum.at(best, sample[found], pairs.distance[found])
    near = np.flatnonzero(apart & touch & (pairs.distance < best[sample]))
    way = np.empty(len(near))
    for first, second in np.unique(links[near], axis=0):
        place = touching.place(int(first), int(second))
        group = (links[near, 0] == first) & (links[near, 1] == second)
        rows = near[group]
        way[group] = shapely.distance(shapely.points(pairs.points[rows]), place) + shapely.distance(
            shapely.points(pairs.nearest[rows]), place
        )
    near = _in_room(pairs, near[way > GAP_DETOUR * pairs.distance[near]], room)
    return np.concatenate([found, near])


def _in_room(pairs: _Pairs, rows: np.ndarray, room: BaseGeometry) -> np.ndarray:
    """The *rows* whose chord lies in *room*."""
    chords = shapely.linestrings(np.stack([pairs.points[rows], pairs.nearest[rows]], axis=1))
    return rows[shapely.covers(room, chords)]

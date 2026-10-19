"""Barrier lines that run along a lake ring share its vertices, bit for bit.

A lake cutoff wall is laid on the lake shore between its two wings, so that
stretch is a line of the ``lakes`` family and of the ``barriers`` family. An
engine must mesh it once: it recognises the stretch by its vertices, which
must then be the same in both families. Before the resampling, each barrier
line is cut where it leaves a ring. The pieces off the rings are resampled as
lines of their own, and the ends of each stretch are fixed nodes of the ring.
After it, the barrier line is put back together with the resampled ring
vertices along each stretch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
import shapely
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, LineFamilySpec

__all__ = ["RING_FAMILY", "BarrierSplit", "split_barriers"]

RING_FAMILY = "lakes"
"""The face family whose rings a barrier may run along."""


@dataclass(frozen=True)
class _Stretch:
    """A part of a barrier line on ring ``ring`` from ``start`` to ``end``."""

    ring: int
    start: np.ndarray
    end: np.ndarray
    middle: np.ndarray


@dataclass(frozen=True)
class BarrierSplit:
    """The families with each barrier line cut off the rings, and how to weld it back.

    ``families`` holds the barrier family with its pieces off the rings in place
    of its lines. ``fixed_points`` are the ends of the stretches on the rings.
    ``layout`` gives, per barrier line, its parts in order: the index of a piece
    in the barrier family, or a stretch.
    """

    families: tuple[LineFamilySpec, ...]
    fixed_points: np.ndarray
    layout: tuple[tuple[int | _Stretch, ...], ...] = ()
    barrier: LineFamilySpec | None = None
    tolerance: float = 0.0

    def welded(self, resampled: Sequence[LineFamilySpec]) -> tuple[LineFamilySpec, ...]:
        """The resampled families with each barrier line made whole again.

        A stretch takes the resampled ring vertices between its ends, and the
        piece next to it ends on that ring vertex.
        """
        if self.barrier is None or not self.layout:
            return tuple(resampled)
        pieces = next((family.lines for family in resampled if family.name == BARRIER_FAMILY), ())
        rings = next(family for family in resampled if family.name == RING_FAMILY).lines
        lines = []
        for parts in self.layout:
            coords: list[np.ndarray] = []
            for part in parts:
                if isinstance(part, _Stretch):
                    run = _ring_run(rings[part.ring], part, self.tolerance)
                    if coords:
                        coords[-1] = coords[-1][:-1]
                    coords.append(run)
                    continue
                piece = shapely.get_coordinates(pieces[part])
                if coords:
                    piece = piece[1:]
                coords.append(piece)
            lines.append(LineString(np.vstack(coords)))
        others = tuple(family for family in resampled if family.name != BARRIER_FAMILY)
        return (*others, replace(self.barrier, lines=tuple(lines)))


def split_barriers(families: Sequence[LineFamilySpec], tolerance: float) -> BarrierSplit:
    """Cut each barrier line where it leaves a ring of the lake family.

    A segment of a barrier line runs along a ring when its two ends and its
    middle lie within *tolerance* [m] of it. Without a barrier or a ring family,
    or without such a segment, the families are kept as they are.
    """
    families = tuple(families)
    barrier = next((family for family in families if family.name == BARRIER_FAMILY), None)
    ring_family = next((family for family in families if family.name == RING_FAMILY), None)
    if barrier is None or ring_family is None:
        return BarrierSplit(families, np.empty((0, 2)))
    rings = ring_family.lines
    pieces: list[LineString] = []
    layout: list[tuple[int | _Stretch, ...]] = []
    ends: list[np.ndarray] = []
    for line in barrier.lines:
        parts: list[int | _Stretch] = []
        for ring, coords in _runs(shapely.get_coordinates(line), rings, tolerance):
            if ring < 0:
                parts.append(len(pieces))
                pieces.append(LineString(coords))
                continue
            middle = shapely.get_coordinates(LineString(coords).interpolate(0.5, normalized=True))[
                0
            ]
            parts.append(_Stretch(ring, coords[0], coords[-1], middle))
            ends.extend([coords[0], coords[-1]])
        layout.append(tuple(parts))
    if not ends:
        return BarrierSplit(families, np.empty((0, 2)))
    split = tuple(family for family in families if family.name != BARRIER_FAMILY)
    if pieces:
        split = (*split, replace(barrier, lines=tuple(pieces)))
    return BarrierSplit(split, np.vstack(ends), tuple(layout), barrier, tolerance)


def _runs(
    coords: np.ndarray, rings: Sequence[LineString], tolerance: float
) -> list[tuple[int, np.ndarray]]:
    """The parts of a line in order: ``(ring, coords)`` on a ring, ``(-1, coords)`` off them."""
    start, stop = coords[:-1], coords[1:]
    probes = shapely.points(np.vstack([start, stop, 0.5 * (start + stop)]))
    count = len(start)
    on = np.full(count, -1, dtype=np.int64)
    for index, ring in enumerate(rings):
        near = shapely.distance(probes, ring) <= tolerance
        hit = near[:count] & near[count : 2 * count] & near[2 * count :] & (on < 0)
        on[hit] = index
    parts: list[tuple[int, np.ndarray]] = []
    first = 0
    for k in range(1, count + 1):
        if k == count or on[k] != on[first]:
            parts.append((int(on[first]), coords[first : k + 1]))
            first = k
    return parts


def _ring_run(ring: LineString, stretch: _Stretch, tolerance: float) -> np.ndarray:
    """The ring vertices from the start of *stretch* to its end, in its direction.

    Of the two ways round a closed ring, the one through the middle of the
    stretch is taken.
    """
    coords = shapely.get_coordinates(ring)
    closed = ring.is_closed
    vertices = coords[:-1] if closed else coords
    first = _vertex_at(vertices, stretch.start, tolerance)
    last = _vertex_at(vertices, stretch.end, tolerance)
    n = len(vertices)
    if not closed:
        step = 1 if last >= first else -1
        return vertices[first : last + step : step]
    forward = vertices[(first + np.arange((last - first) % n + 1)) % n]
    backward = vertices[(first - np.arange((first - last) % n + 1)) % n]
    gap = [
        float(shapely.distance(shapely.Point(stretch.middle), LineString(path)))
        if len(path) > 1
        else np.inf
        for path in (forward, backward)
    ]
    return forward if gap[0] <= gap[1] else backward


def _vertex_at(vertices: np.ndarray, point: np.ndarray, tolerance: float) -> int:
    """The index of the ring vertex on *point*, which resampling made a fixed node."""
    gap = np.hypot(*(vertices - point).T)
    index = int(np.argmin(gap))
    if gap[index] > tolerance:
        raise ValueError(
            f"the barrier stretch end ({point[0]:.3f}, {point[1]:.3f}) is {gap[index]:.3e} m "
            "from the nearest vertex of the resampled lake ring"
        )
    return index

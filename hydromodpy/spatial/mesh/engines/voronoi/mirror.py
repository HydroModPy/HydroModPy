"""Mirror pairs of Berge (2019): the seed geometry that puts a mesh face on a line.

Each vertex ``v`` of a face line gets a circle of radius ``R_v``. The two
circles of a segment cut each other in two points, one on each side of the
segment: the mirror pair. The Voronoi face between the two seeds of a pair is
the perpendicular bisector of the pair, so it lies on the segment, and it runs
from vertex to vertex when no other seed lies inside the circle of either
vertex (Berge's definition 2). Every function here works on arrays in the local
frame of the mesh, in metres.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "MERGE_SHARE",
    "RADIUS_SHARE",
    "SECTOR_MARGIN_RAD",
    "circle_segment_crossings",
    "enforce_eq1",
    "initial_radii",
    "pair_seeds",
    "seed_angle",
    "tip_seeds",
]

RADIUS_SHARE = 0.55
"""Circle radius over the longer incident segment. At 0.55 no seed of a raster
staircase ring falls inside another vertex circle (measured on the Flume domain)."""

SECTOR_MARGIN_RAD = math.radians(10.0)
"""Smallest angle at a vertex between two seeds of a sector that keeps both."""

MERGE_SHARE = 0.15
"""A sector whose shared seed would sit closer than this share of the shorter
segment to both lines is merged instead (Berge fusion)."""

_EQ1_SWEEPS = 64
"""Sweeps of the eq. 1 upper bound before giving up; a line converges in a few."""


def initial_radii(n_nodes: int, segment_nodes: np.ndarray, length: np.ndarray) -> np.ndarray:
    """``R_v = RADIUS_SHARE * max(d)`` over the segments incident to each vertex."""
    longest = np.zeros(n_nodes)
    np.maximum.at(longest, segment_nodes[:, 0], length)
    np.maximum.at(longest, segment_nodes[:, 1], length)
    return RADIUS_SHARE * longest


def enforce_eq1(
    radius: np.ndarray, segment_nodes: np.ndarray, length: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Lower radii until ``|R_i - R_j| <= d_ij`` holds on every segment.

    Returns the radii and a mask of the vertices whose radius was lowered. The
    lower bound ``d_ij <= R_i + R_j`` holds from the start (each radius is at
    least ``RADIUS_SHARE`` of every incident segment) and stays true: a radius
    only drops to its neighbour's radius plus the segment length.
    """
    current = np.array(radius, dtype=float)
    a, b = segment_nodes[:, 0], segment_nodes[:, 1]
    for _ in range(_EQ1_SWEEPS):
        lowered = current.copy()
        np.minimum.at(lowered, a, current[b] + length)
        np.minimum.at(lowered, b, current[a] + length)
        if np.array_equal(lowered, current):
            break
        current = lowered
    return current, current < np.asarray(radius, dtype=float)


def pair_seeds(
    start: np.ndarray, stop: np.ndarray, radius_start: np.ndarray, radius_stop: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The mirror pair of each segment: ``(plus, minus, along, ok)``.

    ``plus`` lies on the left of the segment oriented ``start -> stop``,
    ``minus`` on its right. ``along`` is the distance from ``start`` to the foot
    of the pair on the segment. ``ok`` is false where the two circles do not
    cut each other in two distinct points.
    """
    tangent = stop - start
    length = np.hypot(tangent[:, 0], tangent[:, 1])
    unit = tangent / length[:, None]
    normal = np.column_stack([-unit[:, 1], unit[:, 0]])
    along = (length**2 + radius_start**2 - radius_stop**2) / (2.0 * length)
    height2 = radius_start**2 - along**2
    ok = height2 > (1.0e-9 * length) ** 2
    height = np.sqrt(np.where(ok, height2, 0.0))
    foot = start + along[:, None] * unit
    return foot + height[:, None] * normal, foot - height[:, None] * normal, along, ok


def seed_angle(along: np.ndarray, radius: np.ndarray) -> np.ndarray:
    """Angle [rad] at a vertex between a segment and the seeds of its pair.

    ``along`` is the distance from that vertex to the foot of the pair.
    """
    return np.arccos(np.clip(along / radius, -1.0, 1.0))


def tip_seeds(end: np.ndarray, before: np.ndarray, radius: np.ndarray) -> np.ndarray:
    """The third seed of a free line end: on the outgoing tangent, on the end circle."""
    out = end - before
    out /= np.hypot(out[:, 0], out[:, 1])[:, None]
    return end + radius[:, None] * out


def circle_segment_crossings(
    center: np.ndarray, radius: float, coords: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Points where a circle cuts a polyline, with their distance along the polyline.

    ``coords`` are the polyline vertices ``(k, 2)``; the result is sorted by the
    distance along it.
    """
    start, stop = coords[:-1], coords[1:]
    step = stop - start
    seg_length = np.hypot(step[:, 0], step[:, 1])
    offset = np.concatenate([[0.0], np.cumsum(seg_length)])
    rel = start - center
    qa = (step**2).sum(axis=1)
    qb = 2.0 * (rel * step).sum(axis=1)
    qc = (rel**2).sum(axis=1) - radius**2
    disc = qb**2 - 4.0 * qa * qc
    valid = (disc >= 0.0) & (qa > 0.0)
    root = np.sqrt(np.where(valid, disc, 0.0))
    params = []
    for sign in (-1.0, 1.0):
        t = (-qb + sign * root) / (2.0 * np.where(qa > 0.0, qa, 1.0))
        keep = valid & (t >= 0.0) & (t < 1.0)
        params.append((np.flatnonzero(keep), t[keep]))
    index = np.concatenate([p[0] for p in params])
    t = np.concatenate([p[1] for p in params])
    points = start[index] + t[:, None] * step[index]
    along = offset[index] + t * seg_length[index]
    order = np.argsort(along, kind="stable")
    return points[order], along[order]

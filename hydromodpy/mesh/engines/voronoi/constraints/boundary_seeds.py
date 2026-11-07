"""The seeds along each domain ring, between its corners and fixed positions.

The fixed positions are the corners, the river ends and the face line ends on
the ring, whose circle cuts it. Between two of them the seeds follow the local
size.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import substring

from hydromodpy.mesh.engines.voronoi.constraints.face_pairs import (
    SECTOR_MARGIN_RAD,
    circle_segment_crossings,
    pair_seeds,
    seed_angle,
)
from hydromodpy.mesh.engines.voronoi.constraints.state import (
    LOST_BY_MERGE,
    ConstraintState,
    SeedRole,
    cross_product_z,
    drop_segment_pair,
    unit_vector,
)
from hydromodpy.mesh.planar.geometry import polygon_rings
from hydromodpy.mesh.resample import positions_at_local_size

CORNER_TURN_RAD = math.radians(45.0)
"""A domain ring vertex turning more than this angle is a corner (a fixed boundary seed)."""

BOUNDARY_ANGLE_RAD = math.radians(30.0)
"""A line end on the boundary meeting it under this angle yields its last segment."""


def place_boundary_seeds(state: ConstraintState, *, step: float, pixel: float) -> None:
    """Seeds along every domain ring, between corners, river ends and line ends."""
    river_ends = _river_ends(state)
    for ring_index, line in enumerate(polygon_rings(state.domain)):
        coords = np.asarray(line.coords)
        total = line.length
        start = int(np.lexsort((coords[:-1, 1], coords[:-1, 0]))[0])
        start_s = float(
            np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))])[start]
        )
        on_ring = shapely.distance(shapely.points(river_ends), line) <= state.tol
        fixed: list[tuple[float, np.ndarray | None]] = [
            (float(line.project(Point(xy))), None) for xy in river_ends[on_ring]
        ]
        for xy in _corners(line, pixel):
            s = float(line.project(Point(xy)))
            if all(_ring_gap(s, other, total) > state.tol for other, _ in fixed):
                fixed.append((s, xy))
        gaps = _line_end_seeds(state, line, coords, fixed, total)
        _ring_seeds(state, line, ring_index, fixed, gaps, total, start_s, step)


def _river_ends(state: ConstraintState) -> np.ndarray:
    """The first and last seeds of each river chain."""
    ends = [state.seeds.xy[chain.ids[[0, -1]]] for chain in state.chains if chain.ids.size]
    return np.vstack(ends) if ends else np.empty((0, 2))


def _corners(line: LineString, pixel: float) -> np.ndarray:
    """Vertices of the ring simplified at one pixel that turn by more than 45 degrees."""
    simple = shapely.get_coordinates(shapely.simplify(line, pixel, preserve_topology=False))[:-1]
    if len(simple) < 3:
        return np.empty((0, 2))
    incoming = simple - np.roll(simple, 1, axis=0)
    outgoing = np.roll(simple, -1, axis=0) - simple
    turn = np.abs(
        np.mod(
            np.arctan2(outgoing[:, 1], outgoing[:, 0])
            - np.arctan2(incoming[:, 1], incoming[:, 0])
            + np.pi,
            2.0 * np.pi,
        )
        - np.pi
    )
    return simple[turn > CORNER_TURN_RAD]


def _ring_gap(a: float, b: float, total: float) -> float:
    """Distance along a ring of length *total* between two positions."""
    gap = abs(a - b) % total
    return min(gap, total - gap)


def _line_end_seeds(
    state: ConstraintState,
    line: LineString,
    coords: np.ndarray,
    fixed: list[tuple[float, np.ndarray | None]],
    total: float,
) -> list[tuple[float, float]]:
    """Seeds where the circle of a face line end on the ring cuts it; returns the gaps.

    The end itself gets no seed: its two ring neighbors on the circle and the
    pair of its last segment are its sphere. An end meeting the ring under 30
    degrees, or too close to a corner or another end, yields its segment.
    """
    gaps: list[tuple[float, float]] = []
    taken = [s for s, _ in fixed]
    for vertex in state.end_vertices:
        segments = state.incident(vertex)
        if segments.size != 1 or not state.conformal[segments[0]] or not state.vertex_ok[vertex]:
            continue
        v = state.vertices[vertex]
        if line.distance(Point(v)) > state.tol:
            continue
        segment = int(segments[0])
        s_v = float(line.project(Point(v)))
        points, along = circle_segment_crossings(v, float(state.radius[vertex]), coords)
        placed = _end_neighbours(state, vertex, segment, points, along, s_v, total)
        if (
            placed is None
            or any(_inside_arc(s, placed[0], placed[1], total) for s in taken)
            or any(_arcs_meet(placed[0], placed[1], g[0], g[1], total) for g in gaps)
        ):
            drop_segment_pair(state, segment, LOST_BY_MERGE)
            continue
        s_before, s_after, xy = placed
        sort = np.column_stack(
            [np.ones(2), np.full(2, state.seg_line[segment]), np.ones(2), [2.0, 3.0]]
        )
        state.seeds.add(
            xy,
            SeedRole.BOUNDARY,
            state.h(xy),
            line=int(state.seg_line[segment]),
            family=int(state.seg_family[segment]),
            sort=sort,
            vertex=vertex,
        )
        fixed.extend([(s_before, None), (s_after, None)])
        gaps.append((s_before, s_after))
    return gaps


def _end_neighbours(
    state: ConstraintState,
    vertex: int,
    segment: int,
    points: np.ndarray,
    along: np.ndarray,
    s_v: float,
    total: float,
) -> tuple[float, float, np.ndarray] | None:
    """The circle crossings of the ring next to an end on both sides, or ``None``."""
    if len(points) < 2:
        return None
    after = np.flatnonzero(along > s_v)
    before = np.flatnonzero(along < s_v)
    i_after = int(after[0]) if after.size else 0
    i_before = int(before[-1]) if before.size else len(along) - 1
    if i_after == i_before:
        return None
    s_after = float(along[i_after]) + (0.0 if after.size else total)
    s_before = float(along[i_before]) - (0.0 if before.size else total)
    v = state.vertices[vertex]
    nodes = state.seg_nodes[segment]
    w = state.vertices[nodes[1] if nodes[0] == vertex else nodes[0]]
    inward = unit_vector(w - v)
    radius = state.radius
    _, _, along_pair, _ = pair_seeds(
        state.vertices[nodes[:1]], state.vertices[nodes[1:]], radius[nodes[:1]], radius[nodes[1:]]
    )
    at_vertex = along_pair[0] if nodes[0] == vertex else state.seg_length[segment] - along_pair[0]
    beta = float(seed_angle(np.asarray([at_vertex]), np.asarray([radius[vertex]]))[0])
    sides = []
    for xy in (points[i_before], points[i_after]):
        direction = unit_vector(xy - v)
        alpha = math.acos(max(-1.0, min(1.0, float(np.dot(inward, direction)))))
        if alpha < BOUNDARY_ANGLE_RAD or alpha - beta < SECTOR_MARGIN_RAD:
            return None
        sides.append(cross_product_z(inward, direction) > 0.0)
    if sides[0] == sides[1]:
        return None
    return s_before % total, s_after % total, np.vstack([points[i_before], points[i_after]])


def _inside_arc(s: float, low: float, high: float, total: float) -> bool:
    """Whether position *s* lies on the ring arc from *low* to *high* (counted forward)."""
    return (s - low) % total <= (high - low) % total


def _arcs_meet(a0: float, a1: float, b0: float, b1: float, total: float) -> bool:
    """Whether two forward ring arcs overlap."""
    return _inside_arc(b0, a0, a1, total) or _inside_arc(a0, b0, b1, total)


def _ring_seeds(
    state: ConstraintState,
    line: LineString,
    ring_index: int,
    fixed: list[tuple[float, np.ndarray | None]],
    gaps: list[tuple[float, float]],
    total: float,
    start_s: float,
    step: float,
) -> None:
    """Corner seeds and seeds at the local size between consecutive fixed positions."""
    stops = sorted(fixed, key=lambda item: item[0])
    points: list[np.ndarray] = []
    positions: list[float] = []
    if not stops:
        anchor = np.asarray(line.interpolate(start_s).coords[0])
        stops = [(start_s, anchor)]
    for s, xy in stops:
        if xy is not None:
            points.append(np.asarray(xy, dtype=float))
            positions.append(s)
    for k, (s0, _) in enumerate(stops):
        s1 = stops[(k + 1) % len(stops)][0]
        span = (s1 - s0) % total or total
        if any(
            abs(g0 - s0) <= state.tol and _ring_gap(g1, s1, total) <= state.tol for g0, g1 in gaps
        ):
            continue
        piece = _ring_piece(line, s0, span, total)
        inner, along, _ = positions_at_local_size(piece, step, state.h, ring=len(stops) == 1)
        points.extend(inner)
        positions.extend(((s0 + along) % total).tolist())
    if not points:
        return
    xy = np.vstack(points)
    rel = (np.asarray(positions) - start_s) % total
    sort = np.column_stack(
        [np.full(len(xy), 2.0), np.full(len(xy), ring_index), rel, np.zeros(len(xy))]
    )
    state.seeds.add(xy, SeedRole.BOUNDARY, state.h(xy), line=-1, family=-1, sort=sort)


def _ring_piece(line: LineString, start: float, span: float, total: float) -> LineString:
    """The part of a closed ring from *start* over *span* meters, across its seam if needed."""
    stop = start + span
    if stop <= total:
        return substring(line, start, stop)
    head = shapely.get_coordinates(substring(line, start, total))
    tail = shapely.get_coordinates(substring(line, 0.0, stop - total))
    return LineString(np.vstack([head, tail[1:]]))

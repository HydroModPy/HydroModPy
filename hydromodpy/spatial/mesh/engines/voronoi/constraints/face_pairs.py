"""Mirror pairs of Berge (2019): the seed geometry that puts a mesh face on a line.

Each vertex ``v`` of a face line gets a circle of radius ``R_v``. The two
circles of a segment cut each other in two points, one on each side of the
segment: the mirror pair. The Voronoi face between the two seeds of a pair is
the perpendicular bisector of the pair, so it lies on the segment, and it runs
from vertex to vertex when no other seed lies inside the circle of either
vertex (Berge's definition 2). Every function here works on arrays in the local
frame of the mesh, in metres.

The face graph holds one vertex per millimetre key and the oriented segments of
every face line. A segment gets the pair of its two circles, a free line end a
tip seed, and the seeds of each sector are kept, shared or merged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.engines.voronoi.constraints.lines import _Line
from hydromodpy.spatial.mesh.engines.voronoi.constraints.state import (
    _MERGED,
    SeedRole,
    _demote,
    _State,
)
from hydromodpy.spatial.mesh.model.derived_geometry import vertex_keys

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


def _build_face_graph(state: _State, face_lines: list[_Line]) -> None:
    """Vertices (one per millimetre key) and oriented segments of every face line."""
    if not face_lines:
        state.slot = np.empty((0, 2), dtype=np.int64)
        return
    coords = np.vstack([line.coords for line in face_lines])
    keys = vertex_keys(coords)
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    order = np.argsort(first, kind="stable")
    rank = np.empty(first.size, dtype=np.int64)
    rank[order] = np.arange(first.size)
    node = rank[inverse.ravel()]
    state.vertices = coords[first[order]]
    starts, stops, lines, index = [], [], [], []
    offset = 0
    for line in face_lines:
        ids = node[offset : offset + len(line.coords)]
        offset += len(line.coords)
        keep = ids[:-1] != ids[1:]
        starts.append(ids[:-1][keep])
        stops.append(ids[1:][keep])
        lines.append(np.full(int(keep.sum()), line.gid))
        index.append(np.flatnonzero(keep))
    state.seg_nodes = np.column_stack([np.concatenate(starts), np.concatenate(stops)])
    state.seg_line = np.concatenate(lines).astype(np.int64)
    state.seg_index = np.concatenate(index).astype(np.int64)
    by_gid = {line.gid: line for line in state.lines}
    state.seg_family = np.asarray(
        [by_gid[g].family for g in state.seg_line.tolist()], dtype=np.int64
    )
    step = state.vertices[state.seg_nodes[:, 1]] - state.vertices[state.seg_nodes[:, 0]]
    state.seg_length = np.hypot(step[:, 0], step[:, 1])
    n_seg = len(state.seg_nodes)
    state.conformal = np.ones(n_seg, dtype=bool)
    state.reason = np.zeros(n_seg, dtype=np.int8)
    state.slot = np.full((n_seg, 2), -1, dtype=np.int64)
    n_vertices = len(state.vertices)
    state.vertex_ok = np.ones(n_vertices, dtype=bool)
    state.tip = np.full(n_vertices, -1, dtype=np.int64)


def _alias_shared(state: _State) -> None:
    """The segments of each shared stretch, found on its owner line after the crossings.

    The stretch runs on the owner from the vertex nearest its start to the one
    nearest its end; of the two ways round a ring, the one closer to the
    stretch is taken. A segment is reversed when the stretch runs against it.
    """
    if not state.shared or not len(state.seg_nodes):
        return
    by_gid = {line.gid: line for line in state.lines}
    node_of = {int(key): i for i, key in enumerate(vertex_keys(state.vertices).tolist())}
    segment_of = {(int(a), int(b)): k for k, (a, b) in enumerate(state.seg_nodes.tolist())}
    segments, families, reversed_ = [], [], []
    for stretch in state.shared:
        owner = by_gid[stretch.owner]
        coords = owner.coords[:-1] if owner.closed else owner.coords
        path = _owner_path(coords, stretch.coords, owner.closed)
        nodes = [node_of[int(key)] for key in vertex_keys(coords[path]).tolist()]
        for a, b in zip(nodes[:-1], nodes[1:], strict=True):
            forward = segment_of.get((a, b), -1)
            segment = forward if forward >= 0 else segment_of.get((b, a), -1)
            if segment < 0:
                continue
            segments.append(segment)
            families.append(stretch.family)
            reversed_.append(forward < 0)
    state.alias_segment = np.asarray(segments, dtype=np.int64)
    state.alias_family = np.asarray(families, dtype=np.int64)
    state.alias_reversed = np.asarray(reversed_, dtype=bool)


def _owner_path(coords: np.ndarray, stretch: np.ndarray, closed: bool) -> np.ndarray:
    """Indices of the owner vertices from the start of *stretch* to its end."""
    first = int(np.argmin(np.hypot(*(coords - stretch[0]).T)))
    last = int(np.argmin(np.hypot(*(coords - stretch[-1]).T)))
    n = len(coords)
    if not closed:
        step = 1 if last >= first else -1
        return np.arange(first, last + step, step)
    forward = (first + np.arange((last - first) % n + 1)) % n
    backward = (first - np.arange((first - last) % n + 1)) % n
    line = LineString(stretch)
    gap = [
        float(shapely.distance(shapely.points(coords[path]), line).max())
        for path in (forward, backward)
    ]
    return forward if gap[0] <= gap[1] else backward


def _place_mirror_seeds(state: _State) -> None:
    """Radii, sector rules, then the pairs of the segments that keep them and the tips."""
    if not len(state.seg_nodes):
        state.radius = np.empty(0)
        state.shrunk = np.empty(0, dtype=bool)
        return
    nodes, length = state.seg_nodes, state.seg_length
    start_radius = initial_radii(len(state.vertices), nodes, length)
    radius, _ = enforce_eq1(start_radius, nodes, length)
    sectors = _Sectors.of(state.vertices, nodes)
    shared = _resolve_sectors(state, sectors, radius)
    state.radius = radius
    state.shrunk = radius < start_radius
    plus, minus, _, ok = pair_seeds(
        state.vertices[nodes[:, 0]],
        state.vertices[nodes[:, 1]],
        radius[nodes[:, 0]],
        radius[nodes[:, 1]],
    )
    _merge(state, np.flatnonzero(~ok))
    for q, owners in shared:
        if not all(state.conformal[s] for s, _ in owners):
            continue
        seed = _add_face_seeds(state, q[None, :], np.asarray([owners[0][0]]), owners[0][1])[0]
        for segment, side in owners:
            state.slot[segment, side] = seed
    for side, points in ((0, plus), (1, minus)):
        missing = np.flatnonzero(state.conformal & (state.slot[:, side] < 0))
        if not missing.size:
            continue
        state.slot[missing, side] = _add_face_seeds(state, points[missing], missing, side)
    _place_tips(state)


def _add_face_seeds(state: _State, xy: np.ndarray, segments: np.ndarray, side: int) -> np.ndarray:
    """Mirror seeds of *segments* on one side, sorted by line, segment, side."""
    sort = np.column_stack(
        [
            np.ones(len(segments)),
            state.seg_line[segments],
            np.zeros(len(segments)),
            2.0 * state.seg_index[segments] + side,
        ]
    )
    return state.seeds.add(
        xy,
        SeedRole.MIRROR,
        state.h(xy),
        line=state.seg_line[segments],
        family=state.seg_family[segments],
        sort=sort,
    )


@dataclass(frozen=True)
class _Sectors:
    """The angular sectors at the face vertices of degree two or more.

    Sector ``k`` lies counter-clockwise from half-edge ``first[k]`` to
    half-edge ``second[k]`` around their vertex, with angle ``phi[k]``.
    Half-edge ``e`` runs from ``vertex`` along segment ``segment[e]``,
    ``outgoing[e]`` when the segment starts at the vertex.
    """

    node: np.ndarray
    other: np.ndarray
    segment: np.ndarray
    outgoing: np.ndarray
    theta: np.ndarray
    first: np.ndarray
    second: np.ndarray
    phi: np.ndarray

    @classmethod
    def of(cls, vertices: np.ndarray, nodes: np.ndarray) -> _Sectors:
        """Half-edges sorted by angle around each vertex, and the sectors between them."""
        n_seg = len(nodes)
        node = np.concatenate([nodes[:, 0], nodes[:, 1]])
        other = np.concatenate([nodes[:, 1], nodes[:, 0]])
        segment = np.concatenate([np.arange(n_seg), np.arange(n_seg)])
        outgoing = np.concatenate([np.ones(n_seg, bool), np.zeros(n_seg, bool)])
        step = vertices[other] - vertices[node]
        theta = np.arctan2(step[:, 1], step[:, 0])
        order = np.lexsort((theta, node))
        sorted_node = node[order]
        starts = np.flatnonzero(np.concatenate([[True], sorted_node[1:] != sorted_node[:-1]]))
        counts = np.diff(np.concatenate([starts, [len(order)]]))
        group_start = np.repeat(starts, counts)
        group_size = np.repeat(counts, counts)
        position = np.arange(len(order)) - group_start
        following = order[group_start + (position + 1) % group_size]
        multi = group_size >= 2
        first, second = order[multi], following[multi]
        phi = np.mod(theta[second] - theta[first], 2.0 * np.pi)
        return cls(node, other, segment, outgoing, theta, first, second, phi)

    def facing(
        self, radius: np.ndarray, along: np.ndarray, length: np.ndarray
    ) -> tuple[np.ndarray, ...]:
        """For each sector: the side of each segment facing it and the seed angles there."""
        first, second = self.first, self.second
        side_first = np.where(self.outgoing[first], 0, 1)
        side_second = np.where(self.outgoing[second], 1, 0)
        at_first = np.where(
            self.outgoing[first],
            along[self.segment[first]],
            length[self.segment[first]] - along[self.segment[first]],
        )
        at_second = np.where(
            self.outgoing[second],
            along[self.segment[second]],
            length[self.segment[second]] - along[self.segment[second]],
        )
        vertex_radius = radius[self.node[first]]
        return (
            side_first,
            side_second,
            seed_angle(at_first, vertex_radius),
            seed_angle(at_second, vertex_radius),
        )


def _resolve_sectors(
    state: _State, sectors: _Sectors, radius: np.ndarray
) -> list[tuple[np.ndarray, list[tuple[int, int]]]]:
    """Keep, share or merge the seeds of every sector; adjusts *radius* in place.

    A sector keeps the seeds of both its segments when they are at least
    ``SECTOR_MARGIN_RAD`` apart. Otherwise one seed ``q`` on the vertex circle
    at the bisector serves both, and the far ends of the two segments take
    their distance to ``q`` as radius, so the three circles meet at ``q``.
    When ``q`` would lie too close to the lines (``R sin(phi/2) < 0.15 d``),
    the two segments merge instead and lose their pairs. Returns the shared
    seeds ``(q, [(segment, side), ...])``.
    """
    vertices, nodes, length = state.vertices, state.seg_nodes, state.seg_length
    if not len(sectors.first):
        return []
    _, _, along, _ = pair_seeds(
        vertices[nodes[:, 0]], vertices[nodes[:, 1]], radius[nodes[:, 0]], radius[nodes[:, 1]]
    )
    side_first, side_second, beta_first, beta_second = sectors.facing(radius, along, length)
    phi = sectors.phi
    keep = beta_first + beta_second <= phi - SECTOR_MARGIN_RAD
    seg_first, seg_second = sectors.segment[sectors.first], sectors.segment[sectors.second]
    vertex = sectors.node[sectors.first]
    shortest = np.minimum(length[seg_first], length[seg_second])
    merge = ~keep & (radius[vertex] * np.sin(0.5 * phi) < MERGE_SHARE * shortest)
    _merge(state, np.concatenate([seg_first[merge], seg_second[merge]]))
    assigned: dict[int, float] = {}
    candidates = []
    for k in np.flatnonzero(~keep & ~merge).tolist():
        v = int(vertex[k])
        angle = sectors.theta[sectors.first[k]] + 0.5 * phi[k]
        q = vertices[v] + radius[v] * np.array([math.cos(angle), math.sin(angle)])
        far = (int(sectors.other[sectors.first[k]]), int(sectors.other[sectors.second[k]]))
        wanted = [float(np.hypot(*(q - vertices[w]))) for w in far]
        clash = far[0] == far[1] or any(
            w in assigned and abs(assigned[w] - r) > 1.0e-9 * r
            for w, r in zip(far, wanted, strict=True)
        )
        if clash:
            _merge(state, np.asarray([seg_first[k], seg_second[k]]))
            continue
        assigned.update(zip(far, wanted, strict=True))
        candidates.append((k, v, q))
    for w, r in assigned.items():
        radius[w] = r
    plus, minus, along, ok = pair_seeds(
        vertices[nodes[:, 0]], vertices[nodes[:, 1]], radius[nodes[:, 0]], radius[nodes[:, 1]]
    )
    pairs = np.stack([plus, minus], axis=1)
    shared = []
    used: set[tuple[int, int]] = set()
    for k, v, q in candidates:
        owners = [
            (int(seg_first[k]), int(side_first[k])),
            (int(seg_second[k]), int(side_second[k])),
        ]
        gap = max(float(np.hypot(*(pairs[s, side] - q))) for s, side in owners)
        if (
            gap > 1.0e-9 * radius[v]
            or not all(ok[s] for s, _ in owners)
            or any(o in used for o in owners)
        ):
            _merge(state, np.asarray([s for s, _ in owners]))
            continue
        used.update(owners)
        shared.append((q, owners))
    side_first, side_second, beta_first, beta_second = sectors.facing(radius, along, length)
    late = keep & (beta_first + beta_second > phi - SECTOR_MARGIN_RAD)
    _merge(state, np.concatenate([seg_first[late], seg_second[late]]))
    return shared


def _merge(state: _State, segments: np.ndarray) -> None:
    """Berge fusion: the segments lose their pairs, their cells become mixed."""
    for segment in np.unique(np.asarray(segments, dtype=np.int64)).tolist():
        _demote(state, segment, _MERGED)


def _place_tips(state: _State) -> None:
    """A tip seed past each free line end inside the domain."""
    degree = state.degree()
    ends = np.flatnonzero(degree == 1)
    if not ends.size:
        return
    on_boundary = (
        shapely.distance(shapely.points(state.vertices[ends]), state.domain.boundary) <= state.tol
    )
    state.end_vertices = ends[on_boundary].tolist()
    free = ends[~on_boundary]
    segments = np.asarray([state.incident(int(v))[0] for v in free.tolist()], dtype=np.int64)
    if not segments.size:
        return
    keep = state.conformal[segments]
    state.vertex_ok[free[~keep]] = False
    free, segments = free[keep], segments[keep]
    nodes = state.seg_nodes[segments]
    before = np.where(nodes[:, 0] == free, nodes[:, 1], nodes[:, 0])
    xy = tip_seeds(state.vertices[free], state.vertices[before], state.radius[free])
    sort = np.column_stack(
        [
            np.ones(len(free)),
            state.seg_line[segments],
            np.ones(len(free)),
            np.where(nodes[:, 0] == free, 0.0, 1.0),
        ]
    )
    state.tip[free] = state.seeds.add(
        xy,
        SeedRole.TIP,
        state.h(xy),
        line=state.seg_line[segments],
        family=state.seg_family[segments],
        sort=sort,
        vertex=free,
    )


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

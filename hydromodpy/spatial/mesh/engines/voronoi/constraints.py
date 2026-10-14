"""Constraint seeds of the Voronoi generator: river chains, mirror pairs, boundary.

The constraint seeds are fixed before the free seeds are drawn and never move
in Lloyd. They are, in canonical order (a seed's rank is its cell id):

1. chain seeds: every vertex of a ``cell`` family line (rivers), one seed per
   shared node; two thalwegs closer than half a cell share a seed;
2. face seeds, line by line: the mirror pair of each segment of a ``face``
   family line (Berge 2019), then the tip of a free end and the two seeds of a
   line end on the domain boundary;
3. boundary seeds along each domain ring, between its corners and fixed nodes,
   at the local size.

A face segment keeps its pair only while Berge's definition 2 holds at both
ends: no other seed inside the circle of the vertex. A segment that cannot
(an acute sector, a river, the boundary, a family of higher priority in the
way) yields: its pair is removed and the cells around it are mixed. Where a
river crosses a contact, the river wins: the crossing vertex becomes a
short segment whose pair joins the river chain, off the river by a lateral
offset the chain publishes. Every step works in the local frame of the mesh.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.engines.triangle.families import request_zone_names
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, SizeSampler
from hydromodpy.spatial.mesh.engines.voronoi.gates import BALL_SHRINK, BergeBalls, MirrorFaces
from hydromodpy.spatial.mesh.engines.voronoi.mirror import (
    MERGE_SHARE,
    SECTOR_MARGIN_RAD,
    circle_segment_crossings,
    enforce_eq1,
    initial_radii,
    pair_seeds,
    seed_angle,
    tip_seeds,
)
from hydromodpy.spatial.mesh.planning.resample import positions_at_local_size
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest

__all__ = [
    "FACE_PRIORITY",
    "ChainPlan",
    "ConstraintPlan",
    "ConstraintSeeds",
    "FaceLineState",
    "SeedRole",
    "place_constraints",
]

FACE_PRIORITY = ("lakes", "geology", "barriers", "watershed_boundary")
"""Face families from the highest priority to the lowest; a family
not named here comes after them, by name. A river always wins."""

THALWEG_SHARE = 0.5
"""Two chain seeds of different lines closer than this share of the smaller size share a cell."""

CONFLICT_SHARE = 0.05
"""Two constraint seeds closer than this share of the smaller size: one is dropped."""

MIRROR_CHAIN_SHARE = 0.5
"""A mirror seed closer than this share of ``h(c)`` to a chain seed ``c`` yields."""

CROSSING_ABSORB_SHARE = 0.4
"""Face vertices closer than this share of the local size to a crossing end are absorbed."""

CORNER_TURN_RAD = math.radians(45.0)
"""A domain ring vertex turning more than this angle is a corner (a fixed boundary seed)."""

BOUNDARY_ANGLE_RAD = math.radians(30.0)
"""A line end on the boundary meeting it under this angle yields its last segment."""

BOUNDARY_TOL_REL = 1.0e-6
"""Distance to the domain boundary, as a share of its extent, under which a point lies on it."""

_KEY_STEP_M = 1.0e-3
"""Grid of the vertex keys: two line vertices within the same millimetre are one node."""

_MERGED = 1
_YIELDED = 2


class SeedRole(IntEnum):
    """What a constraint seed is for."""

    CHAIN = 0
    MIRROR = 1
    TIP = 2
    BOUNDARY = 3


_KEEP_PRIORITY = {
    SeedRole.BOUNDARY: 0,
    SeedRole.CHAIN: 1,
    SeedRole.MIRROR: 2,
    SeedRole.TIP: 3,
}


@dataclass(frozen=True, eq=False)
class ConstraintSeeds:
    """The constraint seeds in canonical order, local frame; seed ``i`` becomes cell ``i``.

    ``line_id`` is the canonical line of the seed (``-1`` for a ring seed),
    ``pair_id`` the face segment of a mirror seed, ``vertex_id`` the face
    vertex of a tip or line end seed (``-1`` otherwise). ``radius`` is the
    protection radius ``h(c)`` [m] free seeds keep away from. ``family``
    indexes ``ConstraintPlan.family_names``, ``-1`` for a ring seed.
    """

    xy: np.ndarray
    role: np.ndarray
    line_id: np.ndarray
    pair_id: np.ndarray
    vertex_id: np.ndarray
    radius: np.ndarray
    family: np.ndarray

    @property
    def n(self) -> int:
        """Number of constraint seeds."""
        return int(len(self.xy))


@dataclass(frozen=True, eq=False)
class FaceLineState:
    """The face lines after the Berge rules, local frame.

    ``segment_nodes`` holds each segment ``(start, end)`` along its oriented
    line; ``segment_seeds`` its pair ``(plus, minus)``, ``plus`` on the left,
    ``-1`` when the segment has none. A conformal vertex has every incident
    segment conformal and its sphere complete (tip or boundary end seeds at a
    line end): definition 2 is checked on it alone.
    """

    vertices: np.ndarray
    radius: np.ndarray
    conformal: np.ndarray
    segment_nodes: np.ndarray
    segment_seeds: np.ndarray
    segment_conformal: np.ndarray
    segment_family: np.ndarray
    segment_line: np.ndarray
    zone_left: np.ndarray
    zone_right: np.ndarray


@dataclass(frozen=True, eq=False)
class ChainPlan:
    """The seeds of one cell family line, upstream to downstream, with their offsets [m]."""

    family: str
    line_id: int
    seed_ids: np.ndarray
    offset_m: np.ndarray


@dataclass(frozen=True, eq=False)
class ConstraintPlan:
    """Everything the constraint stage hands to the rest of the generator."""

    seeds: ConstraintSeeds
    faces: FaceLineState
    chains: tuple[ChainPlan, ...]
    family_names: tuple[str, ...]
    zone_names: tuple[str, ...]
    source_lines: Mapping[str, tuple[LineString, ...]]
    family_stats: Mapping[str, Mapping[str, float]]
    notes: tuple[str, ...] = ()

    def seed_extras(self) -> dict[str, float]:
        """Seed counts by role, for the QA ``extras``."""
        role = self.seeds.role
        return {
            "n_seeds_chain": float(np.count_nonzero(role == SeedRole.CHAIN)),
            "n_seeds_mirror": float(np.count_nonzero(role == SeedRole.MIRROR)),
            "n_seeds_tip": float(np.count_nonzero(role == SeedRole.TIP)),
            "n_seeds_boundary": float(np.count_nonzero(role == SeedRole.BOUNDARY)),
        }

    def chain_segments(self) -> tuple[np.ndarray, np.ndarray]:
        """Start and end ``(k, 2)`` of each link between two distinct chain seeds."""
        xy = self.seeds.xy
        starts, ends = [], []
        for chain in self.chains:
            ids = chain.seed_ids
            link = ids[:-1] != ids[1:]
            starts.append(xy[ids[:-1][link]])
            ends.append(xy[ids[1:][link]])
        if not starts:
            return np.empty((0, 2)), np.empty((0, 2))
        return np.vstack(starts), np.vstack(ends)

    def berge_balls(self) -> BergeBalls:
        """The balls of the conformal vertices and the seeds on their spheres (gate G1)."""
        faces = self.faces
        vertices = np.flatnonzero(faces.conformal)
        rank = np.full(len(faces.vertices), -1, dtype=np.int64)
        rank[vertices] = np.arange(vertices.size)
        n_seg = len(faces.segment_nodes)
        node = faces.segment_nodes.T.ravel()
        segment = np.tile(np.arange(n_seg), 2)
        primary = np.lexsort((faces.segment_line[segment], node))
        first = primary[np.unique(node[primary], return_index=True)[1]]
        family = np.full(len(faces.vertices), -1, dtype=np.int64)
        line = np.full(len(faces.vertices), -1, dtype=np.int64)
        family[node[first]] = faces.segment_family[segment[first]]
        line[node[first]] = faces.segment_line[segment[first]]
        sphere = np.flatnonzero(self.seeds.vertex_id >= 0)
        owner = np.concatenate([np.repeat(node, 2), self.seeds.vertex_id[sphere]])
        member = np.concatenate([faces.segment_seeds[segment].ravel(), sphere])
        keep = (member >= 0) & (rank[owner] >= 0)
        pairs = np.unique(np.column_stack([rank[owner[keep]], member[keep]]), axis=0)
        counts = np.bincount(pairs[:, 0], minlength=vertices.size)
        return BergeBalls(
            center=faces.vertices[vertices],
            radius=faces.radius[vertices],
            indptr=np.concatenate([[0], np.cumsum(counts)]),
            members=pairs[:, 1],
            family=family[vertices],
            line_id=line[vertices],
            vertex_id=vertices,
            names=self.family_names,
        )

    def mirror_faces(self) -> MirrorFaces:
        """The faces of the conformal pairs between two conformal vertices (gate G2).

        A run of segments that share one pair (a straight vertex whose two
        sectors share their seeds has only those two seeds on its sphere) is
        one face from the start of the run to its end.
        """
        faces = self.faces
        nodes = faces.segment_nodes
        runs = _pair_runs(faces)
        first, last = runs[:, 0], runs[:, 1]
        keep = faces.conformal[nodes[first, 0]] & faces.conformal[nodes[last, 1]]
        first, last = first[keep], last[keep]
        return MirrorFaces(
            plus=faces.segment_seeds[first, 0],
            minus=faces.segment_seeds[first, 1],
            start=faces.vertices[nodes[first, 0]],
            end=faces.vertices[nodes[last, 1]],
            family=faces.segment_family[first],
            line_id=faces.segment_line[first],
            segment_id=first,
            names=self.family_names,
        )


def _pair_runs(faces: FaceLineState) -> np.ndarray:
    """First and last segment ``(k, 2)`` of each run of conformal segments sharing a pair."""
    segments = np.flatnonzero(faces.segment_conformal & (faces.segment_seeds >= 0).all(axis=1))
    pairs = faces.segment_seeds[segments]
    _, group, count = np.unique(pairs, axis=0, return_inverse=True, return_counts=True)
    group = group.ravel()
    runs = np.column_stack([segments, segments])
    single = count[group] == 1
    merged = []
    for g in np.unique(group[~single]).tolist():
        members = segments[group == g]
        starts = faces.segment_nodes[members, 0]
        stops = faces.segment_nodes[members, 1]
        head = members[~np.isin(starts, stops)]
        tail = members[~np.isin(stops, starts)]
        merged.append([head[0] if head.size else members[0], tail[0] if tail.size else members[-1]])
    if not merged:
        return runs[single]
    runs = np.vstack([runs[single], np.asarray(merged, dtype=np.int64)])
    return runs[np.argsort(runs[:, 0], kind="stable")]


def place_constraints(request: MeshRequest, frame: LocalFrame, h: SizeSampler) -> ConstraintPlan:
    """Place the constraint seeds of *request* in the local *frame*, sizes from *h*."""
    if request.size_field is None:
        raise MeshRequestError("the voronoi generator needs a size field in its request")
    domain = shapely.normalize(frame.to_local(request.domain))
    shapely.prepare(domain)
    xmin, ymin, xmax, ymax = domain.bounds
    tol = BOUNDARY_TOL_REL * max(xmax - xmin, ymax - ymin)
    zone_names = request_zone_names(request)
    specs = sorted(request.lines, key=_family_order)
    family_names = tuple(spec.name for spec in specs)
    state = _State(domain=domain, tol=tol, h=h, family_names=family_names)
    lines, notes = _canonical_lines(specs, frame, domain, tol, zone_names)
    state.lines = lines
    cell_lines = [line for line in lines if specs[line.family].intent == "cell"]
    face_lines = [line for line in lines if specs[line.family].intent == "face"]
    _place_chain_seeds(state, cell_lines)
    crossings = _crossing_face_lines(state, face_lines)
    _build_face_graph(state, face_lines)
    _place_mirror_seeds(state)
    _apply_crossings(state, crossings)
    _settle(state)
    _place_boundary_seeds(state, step=h.h_min / 4.0, pixel=_pixel(request))
    _settle(state)
    return _assemble(state, specs, zone_names, notes)


def _pixel(request: MeshRequest) -> float:
    """The DEM pixel size [m], the tolerance of the corner detection."""
    return max(request.grid.dx, request.grid.dy)


def _family_order(spec: LineFamilySpec) -> tuple[int, int, str]:
    """Cell families first, by name; face families by priority, then by name."""
    if spec.intent == "cell":
        return (0, 0, spec.name)
    if spec.name in FACE_PRIORITY:
        return (1, FACE_PRIORITY.index(spec.name), "")
    return (1, len(FACE_PRIORITY), spec.name)


def _node_keys(xy: np.ndarray) -> np.ndarray:
    """int64 key of each point on a 1 mm grid: equal keys are one node."""
    grid = np.round(np.asarray(xy, dtype=float).reshape(-1, 2) / _KEY_STEP_M).astype(np.int64)
    return grid[:, 0] * np.int64(1 << 32) + (grid[:, 1] + np.int64(1 << 31))


@dataclass
class _Line:
    """One canonical line of the request, in the local frame."""

    gid: int
    family: int
    coords: np.ndarray
    closed: bool
    zone_left: int
    zone_right: int
    source: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))

    def __post_init__(self) -> None:
        """Keep the coordinates as given: a crossing rewrites ``coords``, not ``source``."""
        if not len(self.source):
            self.source = self.coords.copy()


def _line_key(coords: np.ndarray) -> tuple[float, ...]:
    """Sort key of a line: first vertex, last vertex, length, then every coordinate."""
    length = float(np.hypot(*np.diff(coords, axis=0).T).sum())
    head = np.round([*coords[0], *coords[-1], length], 6).tolist()
    return (*head, *coords.ravel().tolist())


def _canonical_lines(
    specs: Sequence[LineFamilySpec],
    frame: LocalFrame,
    domain: Polygon,
    tol: float,
    zone_names: tuple[str, ...],
) -> tuple[list[_Line], tuple[str, ...]]:
    """Every line in the local frame, families in priority order, lines sorted in each.

    A part of a face line that runs along the domain boundary is removed: the
    boundary already bounds the cells there.
    """
    boundary = domain.boundary
    lines: list[_Line] = []
    notes: list[str] = []
    for index, spec in enumerate(specs):
        entries = []
        for k, line in enumerate(spec.lines):
            coords = shapely.get_coordinates(frame.to_local(line))
            left = zone_names.index(spec.zone_left[k]) if spec.zone_left else -1
            right = zone_names.index(spec.zone_right[k]) if spec.zone_right else -1
            closed = bool(spec.closed and np.array_equal(coords[0], coords[-1]))
            entries.append((_line_key(coords), coords, closed, left, right))
        entries.sort(key=lambda entry: entry[0])
        removed = 0.0
        for _, coords, closed, left, right in entries:
            pieces = [(coords, closed)]
            if spec.intent == "face":
                pieces, gone = _off_boundary(coords, closed, boundary, tol)
                removed += gone
            for piece, piece_closed in pieces:
                lines.append(_Line(len(lines), index, piece, piece_closed, left, right))
        if removed > 0.0:
            notes.append(
                f"{spec.name}: {removed:.1f} m of face line along the domain boundary "
                "left to the boundary"
            )
    return lines, tuple(notes)


def _off_boundary(
    coords: np.ndarray, closed: bool, boundary: BaseGeometry, tol: float
) -> tuple[list[tuple[np.ndarray, bool]], float]:
    """The runs of a line off the domain boundary, and the length removed."""
    start, stop = coords[:-1], coords[1:]
    probe = np.vstack([start, stop, 0.5 * (start + stop)])
    near = shapely.distance(shapely.points(probe), boundary) <= tol
    count = len(start)
    on = near[:count] & near[count : 2 * count] & near[2 * count :]
    if not on.any():
        return [(coords, closed)], 0.0
    removed = float(np.hypot(*(stop - start)[on].T).sum())
    order = np.arange(count)
    if closed:
        order = np.roll(order, -(int(np.argmax(on)) + 1))
    runs: list[tuple[np.ndarray, bool]] = []
    current: list[int] = []
    for segment in [*order.tolist(), -1]:
        if segment >= 0 and not on[segment]:
            current.append(segment)
            continue
        if current:
            runs.append((np.vstack([coords[current], coords[current[-1] + 1]]), False))
        current = []
    return runs, removed


class _Seeds:
    """Seeds as they are placed; removed ones stay with ``alive`` false."""

    def __init__(self) -> None:
        self.xy = np.empty((0, 2))
        self.role = np.empty(0, dtype=np.int8)
        self.line = np.empty(0, dtype=np.int64)
        self.vertex = np.empty(0, dtype=np.int64)
        self.family = np.empty(0, dtype=np.int64)
        self.size = np.empty(0)
        self.sort = np.empty((0, 4))
        self.alive = np.empty(0, dtype=bool)
        self.rep = np.empty(0, dtype=np.int64)

    def add(
        self,
        xy: np.ndarray,
        role: SeedRole,
        size: np.ndarray,
        *,
        line: np.ndarray | int,
        family: np.ndarray | int,
        sort: np.ndarray,
        vertex: np.ndarray | int = -1,
    ) -> np.ndarray:
        """Append seeds and return their ids."""
        points = np.asarray(xy, dtype=float).reshape(-1, 2)
        n = len(points)
        first = len(self.xy)
        self.xy = np.vstack([self.xy, points])
        self.role = np.concatenate([self.role, np.full(n, int(role), dtype=np.int8)])
        self.line = np.concatenate([self.line, np.broadcast_to(line, n).astype(np.int64)])
        self.vertex = np.concatenate([self.vertex, np.broadcast_to(vertex, n).astype(np.int64)])
        self.family = np.concatenate([self.family, np.broadcast_to(family, n).astype(np.int64)])
        self.size = np.concatenate([self.size, np.asarray(size, dtype=float).reshape(n)])
        self.sort = np.vstack([self.sort, np.asarray(sort, dtype=float).reshape(n, 4)])
        self.alive = np.concatenate([self.alive, np.ones(n, dtype=bool)])
        self.rep = np.concatenate([self.rep, np.arange(first, first + n, dtype=np.int64)])
        return np.arange(first, first + n, dtype=np.int64)

    def resolved(self, ids: np.ndarray) -> np.ndarray:
        """Follow the replacements of dropped chain seeds to the seed that took their cell."""
        out = np.asarray(ids, dtype=np.int64)
        while True:
            nxt = self.rep[out]
            if np.array_equal(nxt, out):
                return out
            out = nxt


@dataclass
class _Chain:
    """The seeds of one cell line; ``own`` marks the seeds that are vertices of the line."""

    line: _Line
    ids: np.ndarray
    own: np.ndarray


@dataclass
class _Crossing:
    """A river through a face line: the river, its vertex, the new face segment ends."""

    chain: int
    seed: int
    upstream_left: bool
    keys: tuple[int, int]
    segment: int = -1
    active: bool = False
    before_ids: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    before_own: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=bool))
    removed: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))


@dataclass
class _State:
    """The working state of the constraint stage."""

    domain: Polygon
    tol: float
    h: SizeSampler
    family_names: tuple[str, ...]
    cover: Polygon = field(init=False)
    lines: list[_Line] = field(default_factory=list)
    seeds: _Seeds = field(default_factory=_Seeds)
    chains: list[_Chain] = field(default_factory=list)
    shared_cells: int = 0
    vertices: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    radius: np.ndarray = field(default_factory=lambda: np.empty(0))
    shrunk: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=bool))
    vertex_ok: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=bool))
    tip: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    seg_nodes: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.int64))
    seg_line: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    seg_index: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    seg_family: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    seg_length: np.ndarray = field(default_factory=lambda: np.empty(0))
    conformal: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=bool))
    reason: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int8))
    slot: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.int64))
    crossings: list[_Crossing] = field(default_factory=list)
    end_vertices: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        """The domain widened by the boundary tolerance, for the chord tests."""
        self.cover = self.domain.buffer(self.tol)
        shapely.prepare(self.cover)

    def incident(self, vertex: int) -> np.ndarray:
        """The segments of one face vertex."""
        return np.flatnonzero((self.seg_nodes[:, 0] == vertex) | (self.seg_nodes[:, 1] == vertex))

    def degree(self) -> np.ndarray:
        """Number of face segments at each face vertex."""
        return np.bincount(self.seg_nodes.ravel(), minlength=len(self.vertices))

    def crossing_of(self, segment: int) -> _Crossing | None:
        """The active crossing a face segment carries, if any."""
        return next((c for c in self.crossings if c.active and c.segment == segment), None)


# -- Chains ---------------------------------------------------------------------


def _place_chain_seeds(state: _State, cell_lines: list[_Line]) -> None:
    """One seed per node of the cell lines; thalwegs closer than half a cell share one."""
    if not cell_lines:
        return
    coords = np.vstack([line.coords for line in cell_lines])
    keys = _node_keys(coords)
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    rank = np.empty(first.size, dtype=np.int64)
    rank[np.argsort(first, kind="stable")] = np.arange(first.size)
    by_rank = first[np.argsort(first, kind="stable")]
    owner = np.repeat(np.arange(len(cell_lines)), [len(line.coords) for line in cell_lines])
    xy = coords[by_rank]
    ids = state.seeds.add(
        xy,
        SeedRole.CHAIN,
        state.h(xy),
        line=np.asarray([cell_lines[o].gid for o in owner[by_rank]]),
        family=np.asarray([cell_lines[o].family for o in owner[by_rank]]),
        sort=np.column_stack(
            [np.zeros(xy.shape[0]), np.arange(xy.shape[0]), np.zeros((len(xy), 2))]
        ),
    )
    vertex_seed = ids[rank[inverse.ravel()]]
    bounds = np.cumsum([0] + [len(line.coords) for line in cell_lines])
    for k, line in enumerate(cell_lines):
        seq = vertex_seed[bounds[k] : bounds[k + 1]]
        keep = np.concatenate([[True], seq[1:] != seq[:-1]])
        state.chains.append(_Chain(line=line, ids=seq[keep], own=np.ones(int(keep.sum()), bool)))
    _share_thalwegs(state, ids)


def _share_thalwegs(state: _State, ids: np.ndarray) -> None:
    """Drop the later of two chain seeds of different lines closer than half a cell.

    Two seeds share a cell only when the chord between them stays in the
    domain: across a notch of a concave domain their cells cannot meet.
    """
    seeds = state.seeds
    xy = seeds.xy[ids]
    size = seeds.size[ids]
    linked = set()
    for chain in state.chains:
        local = chain.ids - ids[0]
        linked.update(
            zip(
                np.minimum(local[:-1], local[1:]).tolist(),
                np.maximum(local[:-1], local[1:]).tolist(),
                strict=True,
            )
        )
    tree = cKDTree(xy)
    near = tree.query_ball_point(xy, THALWEG_SHARE * size)
    alive = np.ones(len(ids), dtype=bool)
    for j in range(len(ids)):
        best, best_gap = -1, math.inf
        for i in near[j]:
            if i >= j or not alive[i] or (i, j) in linked:
                continue
            gap = float(np.hypot(*(xy[i] - xy[j])))
            if gap < THALWEG_SHARE * min(size[i], size[j]) and gap < best_gap:
                if _chords_inside(state, xy[i][None, :], xy[j][None, :]).all():
                    best, best_gap = i, gap
        if best >= 0:
            alive[j] = False
            seeds.alive[ids[j]] = False
            seeds.rep[ids[j]] = ids[best]
            state.shared_cells += 1
    for chain in state.chains:
        _rechain(state, chain)


def _chords_inside(state: _State, start: np.ndarray, stop: np.ndarray) -> np.ndarray:
    """Whether each chord ``start[i] -> stop[i]`` lies in the domain."""
    chords = shapely.linestrings(np.stack([start, stop], axis=1))
    return shapely.covers(state.cover, chords)


def _rechain(state: _State, chain: _Chain) -> None:
    """Map the chain on the seeds that hold its cells, without removed seeds or repeats.

    A seed removed without a successor (the pair of a crossing undone after
    another chain took it) leaves the chain; the Gabriel rule then checks the
    link that closes the gap.
    """
    resolved = state.seeds.resolved(chain.ids)
    own = chain.own & (resolved == chain.ids)
    alive = state.seeds.alive[resolved]
    resolved, own = resolved[alive], own[alive]
    keep = np.concatenate([[True], resolved[1:] != resolved[:-1]])[: resolved.size]
    chain.ids, chain.own = resolved[keep], own[keep]


# -- Crossings ---------------------------------------------------------------------


@dataclass
class _FaceLine:
    """A face line being edited: its vertices (no closing repeat) and which are fixed."""

    line: _Line
    points: list[np.ndarray]
    fixed: list[bool]


def _crossing_face_lines(state: _State, face_lines: list[_Line]) -> list[_Crossing]:
    """Open each river crossing of a face line into a short segment across the river.

    The crossing vertex ``X`` becomes ``X -/+ (h(X) / 2) t`` along the face
    tangent; face vertices within ``0.4 h(X)`` of the new ends are absorbed.
    The face lines are rewritten in place.
    """
    editable = []
    river_keys: dict[int, int] = {}
    for chain in state.chains:
        for key in _node_keys(chain.line.coords).tolist():
            river_keys[key] = river_keys.get(key, 0) + 1
    occurrences: dict[int, int] = {}
    for line in face_lines:
        points = line.coords[:-1] if line.closed else line.coords
        for key in _node_keys(points).tolist():
            occurrences[key] = occurrences.get(key, 0) + 1
    boundary = state.domain.boundary
    for line in face_lines:
        points = line.coords[:-1] if line.closed else line.coords
        keys = _node_keys(points).tolist()
        on_boundary = shapely.distance(shapely.points(points), boundary) <= state.tol
        fixed = [
            occurrences[key] > 1 or key in river_keys or bool(on_boundary[i])
            for i, key in enumerate(keys)
        ]
        if not line.closed:
            fixed[0] = fixed[-1] = True
        editable.append(_FaceLine(line, list(points), fixed))
    found: list[_Crossing] = []
    face_by_key: dict[int, int] = {}
    for index, face in enumerate(editable):
        for key in _node_keys(np.asarray(face.points)).tolist():
            face_by_key.setdefault(key, index)
    for chain_index, chain in enumerate(state.chains):
        coords = chain.line.coords
        keys = _node_keys(coords).tolist()
        for pos in range(1, len(coords) - 1):
            key = keys[pos]
            if occurrences.get(key) != 1 or river_keys.get(key) != 1:
                continue
            seed = _seed_of(state, chain, coords[pos])
            if seed < 0:
                continue
            crossing = _open_crossing(
                state, editable[face_by_key[key]], key, coords[pos - 1], coords[pos + 1]
            )
            if crossing is not None:
                found.append(
                    _Crossing(
                        chain=chain_index, seed=seed, upstream_left=crossing[0], keys=crossing[1]
                    )
                )
    for face in editable:
        points = np.asarray(face.points)
        face.line.coords = np.vstack([points, points[:1]]) if face.line.closed else points
    return found


def _seed_of(state: _State, chain: _Chain, xy: np.ndarray) -> int:
    """The seed of a vertex of a chain line, ``-1`` when the vertex lost its seed."""
    key = int(_node_keys(xy)[0])
    keys = _node_keys(state.seeds.xy[chain.ids])
    match = np.flatnonzero((keys == key) & chain.own)
    return int(chain.ids[match[0]]) if match.size else -1


def _open_crossing(
    state: _State, face: _FaceLine, key: int, before: np.ndarray, after: np.ndarray
) -> tuple[bool, tuple[int, int]] | None:
    """Replace the crossing vertex of *face* by two ends across the river, or ``None``."""
    points = face.points
    n = len(points)
    found = [i for i, p in enumerate(points) if int(_node_keys(p)[0]) == key]
    if not found:
        return None
    index = found[0]
    if not face.line.closed and index in (0, n - 1):
        return None
    if face.line.closed and n < 4:
        return None
    x = points[index]
    prev_pt, next_pt = points[(index - 1) % n], points[(index + 1) % n]
    tangent = _unit(x - prev_pt) + _unit(next_pt - x)
    if np.hypot(*tangent) == 0.0:
        return None
    tangent = _unit(tangent)
    side_before = _cross(tangent, before - x)
    side_after = _cross(tangent, after - x)
    size = float(state.h(x)[0])
    if side_before * side_after >= 0.0 or min(abs(side_before), abs(side_after)) <= 1.0e-9 * size:
        return None
    low, high = x - 0.5 * size * tangent, x + 0.5 * size * tangent
    if not shapely.intersects_xy(state.domain, *np.vstack([low, high]).T).all():
        return None
    removed: set[int] = set()
    for step, end, sign in ((-1, low, -1.0), (1, high, 1.0)):
        j = index
        while True:
            j = j + step
            if face.line.closed:
                j %= n
            elif not 0 <= j < n:
                return None
            if j == index:
                return None
            v = points[j]
            close = np.hypot(*(v - end)) < CROSSING_ABSORB_SHARE * size
            inside = sign * float(np.dot(v - x, tangent)) < 0.5 * size
            if not (close or inside):
                break
            if face.fixed[j] or j in removed:
                return None
            removed.add(j)
    if face.line.closed and n - len(removed) + 1 < 3:
        return None
    new_points, new_fixed = [], []
    for i, (p, f) in enumerate(zip(points, face.fixed, strict=True)):
        if i in removed:
            continue
        if i == index:
            new_points += [low, high]
            new_fixed += [True, True]
            continue
        new_points.append(p)
        new_fixed.append(f)
    face.points, face.fixed = new_points, new_fixed
    keys = _node_keys(np.vstack([low, high]))
    return side_before > 0.0, (int(keys[0]), int(keys[1]))


def _unit(vector: np.ndarray) -> np.ndarray:
    """The vector over its length."""
    return vector / np.hypot(*vector)


def _cross(a: np.ndarray, b: np.ndarray) -> float:
    """z of the cross product of two plane vectors."""
    return float(a[0] * b[1] - a[1] * b[0])


# -- Face lines and mirror pairs ------------------------------------------------------


def _build_face_graph(state: _State, face_lines: list[_Line]) -> None:
    """Vertices (one per millimetre key) and oriented segments of every face line."""
    if not face_lines:
        state.slot = np.empty((0, 2), dtype=np.int64)
        return
    coords = np.vstack([line.coords for line in face_lines])
    keys = _node_keys(coords)
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


def _apply_crossings(state: _State, crossings: list[_Crossing]) -> None:
    """Put the pair of each crossing segment into its river chain, upstream side first."""
    if not crossings:
        return
    node_of = {int(k): i for i, k in enumerate(_node_keys(state.vertices).tolist())}
    for crossing in crossings:
        a, b = node_of.get(crossing.keys[0]), node_of.get(crossing.keys[1])
        if a is None or b is None:
            continue
        match = np.flatnonzero((state.seg_nodes[:, 0] == a) & (state.seg_nodes[:, 1] == b))
        if not match.size:
            continue
        segment = int(match[0])
        if not state.conformal[segment] or (state.slot[segment] < 0).any():
            continue
        chain = state.chains[crossing.chain]
        xy = state.seeds.xy[chain.ids]
        inside = (np.hypot(*(xy - state.vertices[a]).T) < state.radius[a] * (1.0 + 1.0e-9)) | (
            np.hypot(*(xy - state.vertices[b]).T) < state.radius[b] * (1.0 + 1.0e-9)
        )
        where = np.flatnonzero(inside)
        at = np.flatnonzero(chain.ids == crossing.seed)
        if not at.size or not where.size or at[0] not in where:
            continue
        lo, hi = int(where[0]), int(where[-1])
        if hi - lo + 1 != where.size or lo == 0 or hi == len(chain.ids) - 1:
            continue
        span = chain.ids[lo : hi + 1]
        if not chain.own[lo : hi + 1].all() or any(_uses(state, s) != 1 for s in span.tolist()):
            continue
        plus, minus = state.slot[segment]
        pair = [plus, minus] if crossing.upstream_left else [minus, plus]
        crossing.before_ids, crossing.before_own = chain.ids.copy(), chain.own.copy()
        crossing.removed = span.copy()
        crossing.segment = segment
        crossing.active = True
        chain.ids = np.concatenate([chain.ids[:lo], pair, chain.ids[hi + 1 :]]).astype(np.int64)
        chain.own = np.concatenate([chain.own[:lo], [False, False], chain.own[hi + 1 :]])
        state.seeds.alive[span] = False
    state.crossings = crossings


def _uses(state: _State, seed: int) -> int:
    """How many chain entries hold *seed*."""
    return sum(int(np.count_nonzero(chain.ids == seed)) for chain in state.chains)


def _undo_crossing(state: _State, crossing: _Crossing) -> None:
    """Give the river its own seeds back; the crossing segment then yields to them."""
    chain = state.chains[crossing.chain]
    chain.ids, chain.own = crossing.before_ids, crossing.before_own
    state.seeds.alive[crossing.removed] = True
    crossing.active = False


# -- Settling the conflicts --------------------------------------------------------------


def _demote(state: _State, segment: int, reason: int) -> bool:
    """A segment loses its pair (a shared sector seed stays for its other segment)."""
    crossing = state.crossing_of(segment)
    if crossing is not None:
        _undo_crossing(state, crossing)
    changed = bool(state.conformal[segment])
    if state.conformal[segment]:
        state.conformal[segment] = False
        state.reason[segment] = reason
    for side in (0, 1):
        seed = int(state.slot[segment, side])
        if seed < 0:
            continue
        state.slot[segment, side] = -1
        changed = True
        if not (state.slot == seed).any():
            state.seeds.alive[seed] = False
    return changed


def _remove(state: _State, seed: int, winner: int, reason: int) -> bool:
    """Remove one constraint seed after a conflict; a chain seed hands its cell to *winner*."""
    seeds = state.seeds
    role = SeedRole(int(seeds.role[seed]))
    if role is SeedRole.MIRROR:
        owners = np.flatnonzero((state.slot == seed).any(axis=1))
        return any([_demote(state, int(s), reason) for s in owners.tolist()])
    seeds.alive[seed] = False
    vertex = int(seeds.vertex[seed])
    if role in (SeedRole.CHAIN, SeedRole.BOUNDARY) and winner >= 0:
        seeds.rep[seed] = winner
    if vertex >= 0:
        state.vertex_ok[vertex] = False
        if role is SeedRole.TIP:
            state.tip[vertex] = -1
    return True


def _settle(state: _State) -> None:
    """Resolve conflicts until no constraint seed breaks a rule."""
    while (
        _drop_outside(state)
        or _drop_close(state)
        or _yield_to_chains(state)
        or _clear_chain_links(state)
        or _yield_in_balls(state)
    ):
        pass
    for chain in state.chains:
        _rechain(state, chain)


def _drop_outside(state: _State) -> bool:
    """Mirror and tip seeds outside the domain go, with the segments they belong to."""
    seeds = state.seeds
    probe = np.flatnonzero(
        seeds.alive & ((seeds.role == SeedRole.MIRROR) | (seeds.role == SeedRole.TIP))
    )
    if not probe.size:
        return False
    outside = probe[~shapely.intersects_xy(state.domain, seeds.xy[probe, 0], seeds.xy[probe, 1])]
    return any([_remove(state, int(s), -1, _YIELDED) for s in outside.tolist()])


def _drop_close(state: _State) -> bool:
    """Of two seeds closer than 0.05 size, keep boundary, then chain, then mirror, then tip."""
    seeds = state.seeds
    alive = np.flatnonzero(seeds.alive)
    if alive.size < 2:
        return False
    size = seeds.size[alive]
    pairs = cKDTree(seeds.xy[alive]).query_pairs(
        CONFLICT_SHARE * float(size.max()), output_type="ndarray"
    )
    if not len(pairs):
        return False
    gap = np.hypot(*(seeds.xy[alive[pairs[:, 0]]] - seeds.xy[alive[pairs[:, 1]]]).T)
    pairs = pairs[gap < CONFLICT_SHARE * np.minimum(size[pairs[:, 0]], size[pairs[:, 1]])]
    changed = False
    for i, j in sorted(map(tuple, alive[pairs].tolist())):
        if not (seeds.alive[i] and seeds.alive[j]):
            continue
        rank_i = (_KEEP_PRIORITY[SeedRole(int(seeds.role[i]))], i)
        rank_j = (_KEEP_PRIORITY[SeedRole(int(seeds.role[j]))], j)
        winner, loser = (i, j) if rank_i < rank_j else (j, i)
        changed |= _remove(state, loser, winner, _YIELDED)
    return changed


def _yield_to_chains(state: _State) -> bool:
    """A mirror seed closer than ``0.5 h(c)`` to a chain seed ``c`` yields its segments.

    Next to a crossing the river and the crossed line meet by construction:
    there the Gabriel rule of the chain links decides alone.
    """
    seeds = state.seeds
    chain = np.flatnonzero(seeds.alive & (seeds.role == SeedRole.CHAIN))
    mirror = np.flatnonzero(seeds.alive & (seeds.role == SeedRole.MIRROR))
    mirror = mirror[~np.isin(mirror, sorted(_protected_seeds(state)))]
    if not chain.size or not mirror.size:
        return False
    beside = _beside_crossings(state)
    near = cKDTree(seeds.xy[mirror]).query_ball_point(
        seeds.xy[chain], MIRROR_CHAIN_SHARE * seeds.size[chain]
    )
    losers = {
        int(mirror[k])
        for c, found in zip(chain.tolist(), near, strict=True)
        for k in found
        if int(seeds.line[mirror[k]]) not in beside.get(c, ())
    }
    return any([_remove(state, m, -1, _YIELDED) for m in sorted(losers)])


def _protected_seeds(state: _State) -> set[int]:
    """The pair seeds of the active crossings, which belong to a river chain."""
    return {int(s) for c in state.crossings if c.active for s in state.slot[c.segment]}


def _beside_crossings(state: _State) -> dict[int, set[int]]:
    """Chain seed next to a crossing pair in its chain -> the face lines crossed there."""
    beside: dict[int, set[int]] = {}
    for crossing in state.crossings:
        if not crossing.active:
            continue
        ids = state.chains[crossing.chain].ids
        pair = state.slot[crossing.segment]
        for k in np.flatnonzero(np.isin(ids, pair)).tolist():
            for j in (k - 1, k + 1):
                if 0 <= j < len(ids) and ids[j] not in pair:
                    beside.setdefault(int(ids[j]), set()).add(int(state.seg_line[crossing.segment]))
    return beside


def _clear_chain_links(state: _State) -> bool:
    """Keep the Gabriel disk of every chain link free of other constraint seeds.

    Two seeds whose disk on their link as diameter holds no other seed have
    neighbouring cells, which keeps the chain continuous (gate G3); Lloyd keeps
    the free seeds out. A mirror seed in a disk yields its segments, a tip or a
    boundary seed goes, and a chain seed (or a crossing pair) joins the chain
    between the two: the river passes through its cell.
    """
    seeds = state.seeds
    for chain in state.chains:
        _rechain(state, chain)
    alive = np.flatnonzero(seeds.alive)
    if not alive.size:
        return False
    tree = cKDTree(seeds.xy[alive])
    protected = _protected_seeds(state)
    changed = False
    for chain in state.chains:
        ids = chain.ids
        if ids.size < 2:
            continue
        a, b = seeds.xy[ids[:-1]], seeds.xy[ids[1:]]
        middle = 0.5 * (a + b)
        reach = 0.5 * np.hypot(*(b - a).T)
        found = tree.query_ball_point(middle, reach * (1.0 + 1.0e-9))
        for k, near in enumerate(found):
            intruders = [int(alive[i]) for i in near if alive[i] not in (ids[k], ids[k + 1])]
            if not intruders:
                continue
            gap = [float(np.hypot(*(seeds.xy[i] - middle[k]))) for i in intruders]
            intruder = intruders[int(np.argmin(gap))]
            role = SeedRole(int(seeds.role[intruder]))
            if role is SeedRole.CHAIN or intruder in protected:
                ends = seeds.xy[[ids[k], ids[k + 1]]]
                if not _chords_inside(state, ends, seeds.xy[[intruder, intruder]]).all():
                    continue
                chain.ids = np.insert(ids, k + 1, intruder)
                chain.own = np.insert(chain.own, k + 1, False)
                changed = True
            else:
                changed |= _remove(state, intruder, -1, _YIELDED)
            break
    return changed


def _yield_in_balls(state: _State) -> bool:
    """Definition 2: a seed inside the ball of a conformal vertex makes one side yield.

    A chain or boundary seed always wins. Between two face lines, the family of
    lower priority yields, then the later line. A crossing segment wins
    over every face seed.
    """
    candidates = _conformal_vertices(state)
    seeds = state.seeds
    alive = np.flatnonzero(seeds.alive)
    if not candidates.size or not alive.size:
        return False
    inside = cKDTree(seeds.xy[alive]).query_ball_point(
        state.vertices[candidates], state.radius[candidates] * (1.0 - BALL_SHRINK)
    )
    protected = {c.segment for c in state.crossings if c.active}
    changed = False
    for vertex, found in zip(candidates.tolist(), inside, strict=True):
        if not found:
            continue
        mine = state.incident(vertex)
        if not state.conformal[mine].all():
            continue
        intruder = int(alive[min(found)])
        if not seeds.alive[intruder]:
            continue
        if _vertex_yields(state, mine, intruder, protected):
            changed |= any([_demote(state, int(s), _YIELDED) for s in mine.tolist()])
        else:
            changed |= _remove(state, intruder, -1, _YIELDED)
    return changed


def _conformal_vertices(state: _State) -> np.ndarray:
    """Face vertices whose segments all keep their pair and whose sphere is complete."""
    if not len(state.seg_nodes):
        return np.empty(0, dtype=np.int64)
    broken = np.zeros(len(state.vertices), dtype=bool)
    loose = ~state.conformal
    broken[state.seg_nodes[loose, 0]] = True
    broken[state.seg_nodes[loose, 1]] = True
    return np.flatnonzero(state.vertex_ok & ~broken & (state.degree() > 0))


def _vertex_yields(state: _State, mine: np.ndarray, intruder: int, protected: set[int]) -> bool:
    """Whether the segments *mine* of a vertex yield to the seed *intruder*."""
    seeds = state.seeds
    role = SeedRole(int(seeds.role[intruder]))
    if role in (SeedRole.CHAIN, SeedRole.BOUNDARY):
        return True
    if role is SeedRole.TIP:
        owners = state.incident(int(seeds.vertex[intruder]))
    else:
        owners = np.flatnonzero((state.slot == intruder).any(axis=1))
    mine_protected = bool(protected.intersection(mine.tolist()))
    theirs_protected = bool(protected.intersection(owners.tolist()))
    if mine_protected != theirs_protected:
        return theirs_protected
    rank_mine = min(
        zip(state.seg_family[mine].tolist(), state.seg_line[mine].tolist(), strict=True)
    )
    rank_theirs = min(
        zip(state.seg_family[owners].tolist(), state.seg_line[owners].tolist(), strict=True)
    )
    return rank_mine >= rank_theirs


# -- Boundary --------------------------------------------------------------------------


def _place_boundary_seeds(state: _State, *, step: float, pixel: float) -> None:
    """Seeds along every domain ring, between corners, river ends and line ends."""
    rings = [state.domain.exterior, *state.domain.interiors]
    river_ends = _river_ends(state)
    for ring_index, ring in enumerate(rings):
        line = LineString(ring.coords)
        coords = np.asarray(ring.coords)
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


def _river_ends(state: _State) -> np.ndarray:
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
    state: _State,
    line: LineString,
    coords: np.ndarray,
    fixed: list[tuple[float, np.ndarray | None]],
    total: float,
) -> list[tuple[float, float]]:
    """Seeds where the circle of a face line end on the ring cuts it; returns the gaps.

    The end itself gets no seed: its two ring neighbours on the circle and the
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
            _demote(state, segment, _MERGED)
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
    state: _State,
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
    inward = _unit(w - v)
    radius = state.radius
    _, _, along_pair, _ = pair_seeds(
        state.vertices[nodes[:1]], state.vertices[nodes[1:]], radius[nodes[:1]], radius[nodes[1:]]
    )
    at_vertex = along_pair[0] if nodes[0] == vertex else state.seg_length[segment] - along_pair[0]
    beta = float(seed_angle(np.asarray([at_vertex]), np.asarray([radius[vertex]]))[0])
    sides = []
    for xy in (points[i_before], points[i_after]):
        direction = _unit(xy - v)
        alpha = math.acos(max(-1.0, min(1.0, float(np.dot(inward, direction)))))
        if alpha < BOUNDARY_ANGLE_RAD or alpha - beta < SECTOR_MARGIN_RAD:
            return None
        sides.append(_cross(inward, direction) > 0.0)
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
    state: _State,
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
    """The part of a closed ring from *start* over *span* metres, across its seam if needed."""
    stop = start + span
    if stop <= total:
        return substring(line, start, stop)
    head = shapely.get_coordinates(substring(line, start, total))
    tail = shapely.get_coordinates(substring(line, 0.0, stop - total))
    return LineString(np.vstack([head, tail[1:]]))


# -- Assembly ----------------------------------------------------------------------------


def _assemble(
    state: _State,
    specs: Sequence[LineFamilySpec],
    zone_names: tuple[str, ...],
    notes: tuple[str, ...],
) -> ConstraintPlan:
    """Sort the surviving seeds canonically and build the plan."""
    seeds = state.seeds
    alive = np.flatnonzero(seeds.alive)
    key = seeds.sort[alive]
    order = alive[np.lexsort((key[:, 3], key[:, 2], key[:, 1], key[:, 0]))]
    final = np.full(len(seeds.xy), -1, dtype=np.int64)
    final[order] = np.arange(order.size)
    slot = np.where(state.slot >= 0, final[np.maximum(state.slot, 0)], -1)
    pair_id = np.full(order.size, -1, dtype=np.int64)
    for side in (1, 0):
        has = slot[:, side] >= 0
        segments = np.flatnonzero(has)[::-1]
        pair_id[slot[segments, side]] = segments
    vertex_id = np.where(
        np.isin(seeds.role[order], (SeedRole.TIP, SeedRole.BOUNDARY)), seeds.vertex[order], -1
    )
    constraint = ConstraintSeeds(
        xy=seeds.xy[order],
        role=seeds.role[order],
        line_id=seeds.line[order],
        pair_id=pair_id,
        vertex_id=vertex_id,
        radius=seeds.size[order],
        family=seeds.family[order].astype(np.int16),
    )
    conformal_vertex = np.zeros(len(state.vertices), dtype=bool)
    conformal_vertex[_conformal_vertices(state)] = True
    by_gid = {line.gid: line for line in state.lines}
    faces = FaceLineState(
        vertices=state.vertices,
        radius=state.radius,
        conformal=conformal_vertex,
        segment_nodes=state.seg_nodes,
        segment_seeds=slot,
        segment_conformal=state.conformal.copy(),
        segment_family=state.seg_family,
        segment_line=state.seg_line,
        zone_left=np.asarray(
            [by_gid[g].zone_left for g in state.seg_line.tolist()], dtype=np.int32
        ),
        zone_right=np.asarray(
            [by_gid[g].zone_right for g in state.seg_line.tolist()], dtype=np.int32
        ),
    )
    chains = _chain_plans(state, specs, final, order)
    return ConstraintPlan(
        seeds=constraint,
        faces=faces,
        chains=chains,
        family_names=state.family_names,
        zone_names=zone_names,
        source_lines=_source_lines(state, specs),
        family_stats=_family_stats(state, constraint, faces, chains, specs),
        notes=notes,
    )


def _chain_plans(
    state: _State, specs: Sequence[LineFamilySpec], final: np.ndarray, order: np.ndarray
) -> tuple[ChainPlan, ...]:
    """Each river chain on the final seed ids, with the lateral offset of each cell."""
    plans = []
    for chain in state.chains:
        ids = state.seeds.resolved(chain.ids)
        own = chain.own & (ids == chain.ids)
        ids = final[ids]
        ids, own = ids[ids >= 0], own[ids >= 0]
        keep = np.concatenate([[True], ids[1:] != ids[:-1]])[: ids.size]
        ids, own = ids[keep], own[keep]
        offset = np.zeros(ids.size)
        off = np.flatnonzero(~own)
        if off.size:
            points = shapely.points(state.seeds.xy[order[ids[off]]])
            offset[off] = shapely.distance(points, LineString(chain.line.coords))
        plans.append(
            ChainPlan(
                family=specs[chain.line.family].name,
                line_id=chain.line.gid,
                seed_ids=ids,
                offset_m=offset,
            )
        )
    return tuple(plans)


def _source_lines(
    state: _State, specs: Sequence[LineFamilySpec]
) -> dict[str, tuple[LineString, ...]]:
    """The lines each family was meshed on, local frame (face lines without the crossings)."""
    out: dict[str, list[LineString]] = {spec.name: [] for spec in specs}
    for chain in state.chains:
        out[specs[chain.line.family].name].append(LineString(chain.line.coords))
    for line in state.lines:
        if specs[line.family].intent == "face":
            out[specs[line.family].name].append(LineString(line.source))
    return {name: tuple(lines) for name, lines in out.items()}


def _family_stats(
    state: _State,
    seeds: ConstraintSeeds,
    faces: FaceLineState,
    chains: tuple[ChainPlan, ...],
    specs: Sequence[LineFamilySpec],
) -> dict[str, dict[str, float]]:
    """The QA numbers of each family that the constraint stage knows."""
    stats: dict[str, dict[str, float]] = {}
    open_end = state.degree() == 1
    open_end[state.end_vertices] = False
    open_end &= state.tip < 0
    for index, spec in enumerate(specs):
        if spec.intent == "cell":
            mine_chains = [c for c in chains if c.family == spec.name]
            gids = {c.line_id for c in mine_chains}
            crossings = [
                c for c in state.crossings if c.active and state.chains[c.chain].line.gid in gids
            ]
            offsets = np.asarray(
                [
                    shapely.distance(
                        shapely.points(state.seeds.xy[state.slot[c.segment]]),
                        LineString(state.chains[c.chain].line.coords),
                    ).max()
                    for c in crossings
                ]
            )
            dropped = np.count_nonzero(
                ~state.seeds.alive
                & (state.seeds.role == SeedRole.CHAIN)
                & (state.seeds.family == index)
            )
            stats[spec.name] = {
                "crossings": float(len(crossings)),
                "crossing_offset_m_max": float(offsets.max()) if offsets.size else 0.0,
                "shared_cells": float(state.shared_cells),
                "dropped_seeds": float(dropped - state.shared_cells),
            }
            continue
        mine = state.seg_family == index
        touched = np.zeros(len(state.vertices), dtype=bool)
        touched[state.seg_nodes[mine].ravel()] = True
        length = float(state.seg_length[mine].sum())
        # A free end whose tip seed left the domain keeps its pair but not its last stretch.
        reached = state.conformal & ~open_end[state.seg_nodes].any(axis=1)
        stats[spec.name] = {
            "mirror_pairs": float(np.count_nonzero(mine & state.conformal)),
            "conformal_length_share": float(state.seg_length[mine & reached].sum() / length)
            if length > 0.0
            else float("nan"),
            "def2_vertices": float(np.count_nonzero(touched & faces.conformal)),
            "merged_circles": float(np.count_nonzero(mine & (state.reason == _MERGED))),
            "shrunk_circles": float(np.count_nonzero(touched & state.shrunk)),
            "free_ends": float(
                np.count_nonzero((seeds.role == SeedRole.TIP) & (seeds.family == index))
            ),
            "boundary_ends": float(
                np.count_nonzero((seeds.role == SeedRole.BOUNDARY) & (seeds.family == index)) // 2
            ),
            "yielded_segments": float(np.count_nonzero(mine & (state.reason == _YIELDED))),
        }
    return stats

"""The working state of the constraint stage: seeds, river chains, crossings, face graph.

Every step reads and changes one ``_State``. The operations that remove a seed,
demote a segment or undo a crossing live here with the state, because the river,
mirror pair, conflict and boundary steps all call them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
import shapely
from shapely.geometry import Polygon

from hydromodpy.spatial.mesh.engines.voronoi.constraints.lines import _Line, _Shared
from hydromodpy.spatial.mesh.engines.voronoi.frame import SizeSampler

__all__ = ["BALL_SHRINK", "SeedRole"]

BALL_SHRINK = 1.0e-9
"""Definition 2 tests the open ball ``R_v (1 - BALL_SHRINK)``: the sphere seeds lie on its edge."""

_MERGED = 1

_YIELDED = 2


class SeedRole(IntEnum):
    """What a constraint seed is for."""

    CHAIN = 0
    MIRROR = 1
    TIP = 2
    BOUNDARY = 3


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
    shared: list[_Shared] = field(default_factory=list)
    alias_segment: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    alias_family: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    alias_reversed: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=bool))
    ring_areas: dict[int, Polygon] = field(default_factory=dict)

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


def _unit(vector: np.ndarray) -> np.ndarray:
    """The vector over its length."""
    return vector / np.hypot(*vector)


def _cross(a: np.ndarray, b: np.ndarray) -> float:
    """z of the cross product of two plane vectors."""
    return float(a[0] * b[1] - a[1] * b[0])


def _undo_crossing(state: _State, crossing: _Crossing) -> None:
    """Give the river its own seeds back; the crossing segment then yields to them."""
    chain = state.chains[crossing.chain]
    chain.ids, chain.own = crossing.before_ids, crossing.before_own
    state.seeds.alive[crossing.removed] = True
    crossing.active = False


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


def _conformal_vertices(state: _State) -> np.ndarray:
    """Face vertices whose segments all keep their pair and whose sphere is complete."""
    if not len(state.seg_nodes):
        return np.empty(0, dtype=np.int64)
    broken = np.zeros(len(state.vertices), dtype=bool)
    loose = ~state.conformal
    broken[state.seg_nodes[loose, 0]] = True
    broken[state.seg_nodes[loose, 1]] = True
    return np.flatnonzero(state.vertex_ok & ~broken & (state.degree() > 0))

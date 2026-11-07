"""The river chains: one seed per node of a cell line, and the crossings of the face lines.

Two thalwegs closer than half a cell share a seed. Where a river crosses a face
line, the crossing vertex opens into a short segment across the river, and the
pair of that segment joins the river chain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from scipy.spatial import cKDTree

from hydromodpy.mesh.engines.voronoi.constraints.lines import CanonicalLine
from hydromodpy.mesh.engines.voronoi.constraints.state import (
    ConstraintState,
    RiverChain,
    RiverCrossing,
    SeedRole,
    chords_inside_domain,
    cross_product_z,
    remap_chain,
    unit_vector,
)
from hydromodpy.mesh.planar.geometry import vertex_keys

THALWEG_SHARE = 0.5
"""Two chain seeds of different lines closer than this share of the smaller size share a cell."""

CROSSING_ABSORB_SHARE = 0.4
"""Face vertices closer than this share of the local size to a crossing end are absorbed."""


def place_chain_seeds(state: ConstraintState, cell_lines: list[CanonicalLine]) -> None:
    """One seed per node of the cell lines; thalwegs closer than half a cell share one."""
    if not cell_lines:
        return
    coords = np.vstack([line.coords for line in cell_lines])
    keys = vertex_keys(coords)
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
        state.chains.append(
            RiverChain(line=line, ids=seq[keep], own=np.ones(int(keep.sum()), bool))
        )
    _share_thalwegs(state, ids)


def _share_thalwegs(state: ConstraintState, ids: np.ndarray) -> None:
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
                if chords_inside_domain(state, xy[i][None, :], xy[j][None, :]).all():
                    best, best_gap = i, gap
        if best >= 0:
            alive[j] = False
            seeds.alive[ids[j]] = False
            seeds.successor[ids[j]] = ids[best]
            state.shared_cells += 1
    for chain in state.chains:
        remap_chain(state, chain)


@dataclass
class _FaceLine:
    """A face line being edited: its vertices (no closing repeat) and which are fixed."""

    line: CanonicalLine
    points: list[np.ndarray]
    fixed: list[bool]


def open_river_crossings(
    state: ConstraintState, face_lines: list[CanonicalLine]
) -> list[RiverCrossing]:
    """Open each river crossing of a face line into a short segment across the river.

    The crossing vertex ``X`` becomes ``X -/+ (h(X) / 2) t`` along the face
    tangent; face vertices within ``0.4 h(X)`` of the new ends are absorbed.
    The face lines are rewritten in place.
    """
    editable = []
    river_keys: dict[int, int] = {}
    for chain in state.chains:
        for key in vertex_keys(chain.line.coords).tolist():
            river_keys[key] = river_keys.get(key, 0) + 1
    occurrences: dict[int, int] = {}
    for line in face_lines:
        points = line.coords[:-1] if line.closed else line.coords
        for key in vertex_keys(points).tolist():
            occurrences[key] = occurrences.get(key, 0) + 1
    boundary = state.domain.boundary
    for line in face_lines:
        points = line.coords[:-1] if line.closed else line.coords
        keys = vertex_keys(points).tolist()
        on_boundary = shapely.distance(shapely.points(points), boundary) <= state.tol
        fixed = [
            occurrences[key] > 1 or key in river_keys or bool(on_boundary[i])
            for i, key in enumerate(keys)
        ]
        if not line.closed:
            fixed[0] = fixed[-1] = True
        editable.append(_FaceLine(line, list(points), fixed))
    found: list[RiverCrossing] = []
    face_by_key: dict[int, int] = {}
    for index, face in enumerate(editable):
        for key in vertex_keys(np.asarray(face.points)).tolist():
            face_by_key.setdefault(key, index)
    for chain_index, chain in enumerate(state.chains):
        coords = chain.line.coords
        keys = vertex_keys(coords).tolist()
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
                    RiverCrossing(
                        chain=chain_index, seed=seed, upstream_left=crossing[0], keys=crossing[1]
                    )
                )
    for face in editable:
        points = np.asarray(face.points)
        face.line.coords = np.vstack([points, points[:1]]) if face.line.closed else points
    return found


def _seed_of(state: ConstraintState, chain: RiverChain, xy: np.ndarray) -> int:
    """The seed of a vertex of a chain line, ``-1`` when the vertex lost its seed."""
    key = int(vertex_keys(xy)[0])
    keys = vertex_keys(state.seeds.xy[chain.ids])
    match = np.flatnonzero((keys == key) & chain.own)
    return int(chain.ids[match[0]]) if match.size else -1


def _open_crossing(
    state: ConstraintState, face: _FaceLine, key: int, before: np.ndarray, after: np.ndarray
) -> tuple[bool, tuple[int, int]] | None:
    """Replace the crossing vertex of *face* by two ends across the river, or ``None``."""
    points = face.points
    n = len(points)
    found = [i for i, p in enumerate(points) if int(vertex_keys(p)[0]) == key]
    if not found:
        return None
    index = found[0]
    if not face.line.closed and index in (0, n - 1):
        return None
    if face.line.closed and n < 4:
        return None
    x = points[index]
    prev_pt, next_pt = points[(index - 1) % n], points[(index + 1) % n]
    tangent = unit_vector(x - prev_pt) + unit_vector(next_pt - x)
    if np.hypot(*tangent) == 0.0:
        return None
    tangent = unit_vector(tangent)
    side_before = cross_product_z(tangent, before - x)
    side_after = cross_product_z(tangent, after - x)
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
    keys = vertex_keys(np.vstack([low, high]))
    return side_before > 0.0, (int(keys[0]), int(keys[1]))


def join_crossing_pairs(state: ConstraintState, crossings: list[RiverCrossing]) -> None:
    """Put the pair of each crossing segment into its river chain, upstream side first."""
    if not crossings:
        return
    node_of = {int(k): i for i, k in enumerate(vertex_keys(state.vertices).tolist())}
    for crossing in crossings:
        a, b = node_of.get(crossing.keys[0]), node_of.get(crossing.keys[1])
        if a is None or b is None:
            continue
        match = np.flatnonzero((state.seg_nodes[:, 0] == a) & (state.seg_nodes[:, 1] == b))
        if not match.size:
            continue
        segment = int(match[0])
        if not state.conformal[segment] or (state.segment_seeds[segment] < 0).any():
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
        if not chain.own[lo : hi + 1].all() or any(
            _count_in_chains(state, s) != 1 for s in span.tolist()
        ):
            continue
        plus, minus = state.segment_seeds[segment]
        pair = [plus, minus] if crossing.upstream_left else [minus, plus]
        crossing.before_ids, crossing.before_own = chain.ids.copy(), chain.own.copy()
        crossing.removed = span.copy()
        crossing.segment = segment
        crossing.active = True
        chain.ids = np.concatenate([chain.ids[:lo], pair, chain.ids[hi + 1 :]]).astype(np.int64)
        chain.own = np.concatenate([chain.own[:lo], [False, False], chain.own[hi + 1 :]])
        state.seeds.alive[span] = False
    state.crossings = crossings


def _count_in_chains(state: ConstraintState, seed: int) -> int:
    """How many chain entries hold *seed*."""
    return sum(int(np.count_nonzero(chain.ids == seed)) for chain in state.chains)

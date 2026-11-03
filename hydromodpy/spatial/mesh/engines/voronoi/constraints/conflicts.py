"""The conflict rules, applied until no constraint seed breaks one.

A seed outside the domain or too close to another goes. A face segment yields
to a river, except a barrier or a lake shore (``RIVER_PROOF_FAMILIES``). A chain
link keeps its Gabriel disk free, and a conformal vertex keeps its Berge ball
free of any other seed.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import Polygon

from hydromodpy.spatial.mesh.engines.voronoi.constraints.state import (
    CIRCLE_SHRINK,
    LOST_BY_CONFLICT,
    ConstraintState,
    RiverChain,
    SeedRole,
    chords_inside_domain,
    conformal_vertices,
    cross_product_z,
    drop_segment_pair,
    remap_chain,
    remove_seed,
)
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY

__all__ = ["LAKE_FAMILY", "RIVER_PROOF_FAMILIES", "resolve_conflicts"]

LAKE_FAMILY = "lakes"
"""The face family of the lake shores."""

RIVER_PROOF_FAMILIES = (LAKE_FAMILY, BARRIER_FAMILY)
"""Face families that never yield to a river: a chain seed in their way goes,
and the river passes through the cell of one of their mirror seeds. The lake
regions stay closed, and a barrier face stays between two cells."""

CONFLICT_SHARE = 0.05
"""Two constraint seeds closer than this share of the smaller size: one is dropped."""

MIRROR_CHAIN_SHARE = 0.5
"""A mirror seed closer than this share of ``h(c)`` to a chain seed ``c`` yields."""

_KEEP_PRIORITY = {
    SeedRole.BOUNDARY: 0,
    SeedRole.CHAIN: 1,
    SeedRole.MIRROR: 2,
    SeedRole.FREE_END: 3,
}


def resolve_conflicts(state: ConstraintState) -> None:
    """Resolve conflicts until no constraint seed breaks a rule."""
    while (
        _drop_outside(state)
        or _drop_close(state)
        or _clear_around_chain_seeds(state)
        or _clear_chain_links(state)
        or _clear_vertex_circles(state)
    ):
        pass
    for chain in state.chains:
        remap_chain(state, chain)


def _drop_outside(state: ConstraintState) -> bool:
    """Mirror and tip seeds outside the domain go, with the segments they belong to."""
    seeds = state.seeds
    probe = np.flatnonzero(
        seeds.alive & ((seeds.role == SeedRole.MIRROR) | (seeds.role == SeedRole.FREE_END))
    )
    if not probe.size:
        return False
    outside = probe[~shapely.intersects_xy(state.domain, seeds.xy[probe, 0], seeds.xy[probe, 1])]
    return any([remove_seed(state, int(s), -1, LOST_BY_CONFLICT) for s in outside.tolist()])


def _drop_close(state: ConstraintState) -> bool:
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
        changed |= remove_seed(state, loser, winner, LOST_BY_CONFLICT)
    return changed


def _clear_around_chain_seeds(state: ConstraintState) -> bool:
    """A mirror seed closer than ``0.5 h(c)`` to a chain seed ``c`` yields its segments.

    Next to a crossing the river and the crossed line meet by construction:
    there the Gabriel rule of the chain links decides alone. A barrier or a
    lake shore never yields: the chain seed goes instead, and the river passes
    through the cell of the nearest of its mirror seeds, on the river's side of
    a lake shore when one lies there.
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
    river_proof = np.asarray([_is_river_proof(state, int(m)) for m in mirror.tolist()], dtype=bool)
    losers: set[int] = set()
    taken: dict[int, int] = {}
    for c, found in zip(chain.tolist(), near, strict=True):
        found = [k for k in found if int(seeds.line[mirror[k]]) not in beside.get(c, ())]
        walls = [int(mirror[k]) for k in found if river_proof[k]]
        if walls:
            taken[c] = _mirror_seed_for_river(state, walls, seeds.xy[c])
            continue
        losers.update(int(mirror[k]) for k in found)
    changed = [remove_seed(state, c, m, LOST_BY_CONFLICT) for c, m in sorted(taken.items())]
    return any(changed + [remove_seed(state, m, -1, LOST_BY_CONFLICT) for m in sorted(losers)])


def _is_river_proof(state: ConstraintState, seed: int) -> bool:
    """Whether a face seed belongs to a family that never yields to a river."""
    family = int(state.seeds.family[seed])
    return family >= 0 and state.family_names[family] in RIVER_PROOF_FAMILIES


def _on_its_side(state: ConstraintState, seed: int, xy: np.ndarray) -> bool:
    """Whether *xy* lies on the same side of its lake shore as the mirror seed *seed*.

    On a closed ring the side is inside or outside the ring, which holds at a
    corner too; on a ring the domain cut open, the side of the segment of the
    seed. Always true for a seed of another family: a barrier has no inside.
    """
    family = int(state.seeds.family[seed])
    if family < 0 or state.family_names[family] != LAKE_FAMILY:
        return True
    point = np.asarray(xy, dtype=float)
    ring = _ring_area(state, int(state.seeds.line[seed]))
    if ring is not None:
        inside = shapely.contains_xy(ring, *state.seeds.xy[seed])
        return bool(inside == shapely.contains_xy(ring, *point))
    rows, sides = np.nonzero(state.segment_seeds == seed)
    if not rows.size:
        return True
    start, stop = state.vertices[state.seg_nodes[rows[0]]]
    left = cross_product_z(stop - start, point - start) > 0.0
    return left == (int(sides[0]) == 0)


def _ring_area(state: ConstraintState, gid: int) -> Polygon | None:
    """The area a closed face line encloses, or None for an open line."""
    if gid not in state.ring_areas:
        line = next((line for line in state.lines if line.gid == gid), None)
        area = None
        if line is not None and line.closed and len(line.coords) >= 4:
            area = Polygon(line.coords)
            shapely.prepare(area)
        state.ring_areas[gid] = area
    return state.ring_areas[gid]


def _mirror_seed_for_river(
    state: ConstraintState, candidates: Sequence[int], xy: np.ndarray
) -> int:
    """The mirror seed whose cell a river takes at *xy*: the nearest on its side, else the nearest."""
    seeds = state.seeds
    own = [seed for seed in candidates if _on_its_side(state, seed, xy)]
    pool = own or list(candidates)
    gap = [float(np.hypot(*(seeds.xy[seed] - xy))) for seed in pool]
    return int(pool[int(np.argmin(gap))])


def _protected_seeds(state: ConstraintState) -> set[int]:
    """The mirror seeds that belong to a river chain: crossing pairs, joined barrier seeds."""
    crossing = {int(s) for c in state.crossings if c.active for s in state.segment_seeds[c.segment]}
    mirror = state.seeds.role == SeedRole.MIRROR
    joined = {
        int(s)
        for chain in state.chains
        for s in state.seeds.resolved(chain.ids).tolist()
        if mirror[s]
    }
    return crossing | joined


def _joins_chain(state: ConstraintState, seed: int, chain: RiverChain, ends: np.ndarray) -> bool:
    """Whether a mirror seed in the disk of a chain link joins the chain.

    A barrier never yields to a river: the river passes through the cell of
    the mirror seed instead, and the barrier face stays between two cells. A
    lake shore does the same with a seed on the side of both link *ends*; a
    seed across the shore yields, so the river never enters the lake there.
    """
    return (
        int(state.seeds.role[seed]) == SeedRole.MIRROR
        and _is_river_proof(state, seed)
        and all(_on_its_side(state, seed, end) for end in ends)
        and not np.isin(seed, state.seeds.resolved(chain.ids))
    )


def _beside_crossings(state: ConstraintState) -> dict[int, set[int]]:
    """Chain seed next to a crossing pair in its chain -> the face lines crossed there."""
    beside: dict[int, set[int]] = {}
    for crossing in state.crossings:
        if not crossing.active:
            continue
        ids = state.chains[crossing.chain].ids
        pair = state.segment_seeds[crossing.segment]
        for k in np.flatnonzero(np.isin(ids, pair)).tolist():
            for j in (k - 1, k + 1):
                if 0 <= j < len(ids) and ids[j] not in pair:
                    beside.setdefault(int(ids[j]), set()).add(int(state.seg_line[crossing.segment]))
    return beside


def _clear_chain_links(state: ConstraintState) -> bool:
    """Keep the Gabriel disk of every chain link free of other constraint seeds.

    Two seeds whose disk on their link as diameter holds no other seed have
    neighboring cells, which keeps the chain continuous (gate G3); Lloyd keeps
    the free seeds out. A mirror seed in a disk yields its segments, a tip or a
    boundary seed goes, and a chain seed (or a crossing pair) joins the chain
    between the two: the river passes through its cell.
    """
    seeds = state.seeds
    for chain in state.chains:
        remap_chain(state, chain)
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
            if (
                role is SeedRole.CHAIN
                or intruder in protected
                or _joins_chain(state, intruder, chain, seeds.xy[[ids[k], ids[k + 1]]])
            ):
                ends = seeds.xy[[ids[k], ids[k + 1]]]
                if not chords_inside_domain(state, ends, seeds.xy[[intruder, intruder]]).all():
                    continue
                chain.ids = np.insert(ids, k + 1, intruder)
                chain.own = np.insert(chain.own, k + 1, False)
                changed = True
            else:
                changed |= remove_seed(state, intruder, -1, LOST_BY_CONFLICT)
            break
    return changed


def _clear_vertex_circles(state: ConstraintState) -> bool:
    """Definition 2: a seed inside the ball of a conformal vertex makes one side yield.

    A chain or boundary seed always wins, except over a barrier: a chain seed
    in the ball of a barrier vertex goes, and the river passes through the
    cell of the nearest pair seed of that vertex. Between two face lines, the
    family of lower priority yields, then the later line. A crossing segment
    wins over every face seed.
    """
    candidates = conformal_vertices(state)
    seeds = state.seeds
    alive = np.flatnonzero(seeds.alive)
    if not candidates.size or not alive.size:
        return False
    inside = cKDTree(seeds.xy[alive]).query_ball_point(
        state.vertices[candidates], state.radius[candidates] * (1.0 - CIRCLE_SHRINK)
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
        successor = _vertex_seed_for_river(state, mine, intruder)
        if successor >= 0:
            changed |= remove_seed(state, intruder, successor, LOST_BY_CONFLICT)
        elif _vertex_loses_pairs(state, mine, intruder, protected):
            changed |= any(
                [drop_segment_pair(state, int(s), LOST_BY_CONFLICT) for s in mine.tolist()]
            )
        else:
            changed |= remove_seed(state, intruder, -1, LOST_BY_CONFLICT)
    return changed


def _vertex_seed_for_river(state: ConstraintState, mine: np.ndarray, intruder: int) -> int:
    """The pair seed that takes the cell of a chain seed in the ball of a river-proof vertex.

    ``-1`` unless *intruder* is a chain seed and every segment of the vertex
    belongs to a barrier or a lake shore; else the nearest alive pair seed of
    them, on the river's side of a lake shore when one lies there.
    """
    seeds = state.seeds
    if int(seeds.role[intruder]) != SeedRole.CHAIN:
        return -1
    if any(state.family_names[int(f)] not in RIVER_PROOF_FAMILIES for f in state.seg_family[mine]):
        return -1
    pair = state.segment_seeds[mine].ravel()
    pair = pair[(pair >= 0)]
    pair = pair[seeds.alive[pair]]
    if not pair.size:
        return -1
    return _mirror_seed_for_river(state, pair.tolist(), seeds.xy[intruder])


def _vertex_loses_pairs(
    state: ConstraintState, mine: np.ndarray, intruder: int, protected: set[int]
) -> bool:
    """Whether the segments *mine* of a vertex yield to the seed *intruder*."""
    seeds = state.seeds
    role = SeedRole(int(seeds.role[intruder]))
    if role in (SeedRole.CHAIN, SeedRole.BOUNDARY):
        return True
    if role is SeedRole.FREE_END:
        owners = state.incident(int(seeds.vertex[intruder]))
    else:
        owners = np.flatnonzero((state.segment_seeds == intruder).any(axis=1))
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

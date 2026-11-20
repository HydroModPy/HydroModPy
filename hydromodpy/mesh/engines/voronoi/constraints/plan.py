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
way) yields: its pair is removed and the cells around it are mixed. A barrier
or a lake shore does not yield to a river: the river passes through the cell
of one of its mirror seeds. Where a river crosses a contact, the river wins:
the crossing vertex becomes a short segment whose pair joins the river chain,
off the river by a lateral offset the chain publishes. A face line that runs
on segments of an earlier face line (a lake cutoff wall along the lake shore)
leaves that stretch to it: the segment gets one pair, and its face belongs to
both families. Every step works in the local frame of the mesh.

``place_constraints`` runs the steps in order, each in its own module of this
package: the lines (``lines.py``), the river chains and their crossings
(``rivers.py``), the face graph and the mirror pairs (``face_pairs.py``), the
conflicts (``conflicts.py``) and the boundary seeds (``boundary_seeds.py``).
They all work on the state of ``state.py``. This module assembles the result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.engines.face_families import request_zone_names
from hydromodpy.mesh.engines.voronoi.constraints.boundary_seeds import place_boundary_seeds
from hydromodpy.mesh.engines.voronoi.constraints.conflicts import resolve_conflicts
from hydromodpy.mesh.engines.voronoi.constraints.face_pairs import (
    build_face_graph,
    locate_shared_segments,
    place_mirror_seeds,
)
from hydromodpy.mesh.engines.voronoi.constraints.lines import (
    canonical_lines,
    family_sort_key,
)
from hydromodpy.mesh.engines.voronoi.constraints.rivers import (
    join_crossing_pairs,
    open_river_crossings,
    place_chain_seeds,
)
from hydromodpy.mesh.engines.voronoi.constraints.state import (
    LOST_BY_CONFLICT,
    LOST_BY_MERGE,
    ConstraintState,
    SeedRole,
    conformal_vertices,
)
from hydromodpy.mesh.engines.voronoi.local_coords import LocalFrame, SizeSampler
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain
from hydromodpy.mesh.request import LineFamilySpec, MeshRequest

__all__ = ["ConstraintPlan", "ConstraintSeeds", "FaceLineState", "place_constraints"]

BOUNDARY_TOL_REL = 1.0e-6
"""Distance to the domain boundary, as a share of its extent, under which a point lies on it."""


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
    line end): definition 2 is checked on it alone. Segment
    ``shared_segment[k]`` also belongs to family ``shared_family[k]``, whose line
    runs against it where ``shared_reversed[k]``.
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
    shared_segment: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    shared_family: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    shared_reversed: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=bool))


@dataclass(frozen=True, eq=False)
class ConstraintPlan:
    """Everything the constraint stage hands to the rest of the generator.

    ``chains`` holds one chain per river chain, ``chain_id`` its rank. Its
    cell ids are the ids of its seeds, with their lateral offsets.
    """

    seeds: ConstraintSeeds
    faces: FaceLineState
    chains: tuple[CellChain, ...]
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
            "n_seeds_tip": float(np.count_nonzero(role == SeedRole.FREE_END)),
            "n_seeds_boundary": float(np.count_nonzero(role == SeedRole.BOUNDARY)),
        }


def place_constraints(request: MeshRequest, frame: LocalFrame, h: SizeSampler) -> ConstraintPlan:
    """Place the constraint seeds of *request* in the local *frame*, sizes from *h*."""
    if request.size_field is None:
        raise MeshRequestError("the voronoi generator needs a size field in its request")
    domain = shapely.normalize(frame.to_local(request.domain))
    shapely.prepare(domain)
    xmin, ymin, xmax, ymax = domain.bounds
    tol = BOUNDARY_TOL_REL * max(xmax - xmin, ymax - ymin)
    zone_names = request_zone_names(request)
    specs = sorted(request.lines, key=family_sort_key)
    family_names = tuple(spec.name for spec in specs)
    state = ConstraintState(domain=domain, tol=tol, h=h, family_names=family_names)
    lines, shared, notes = canonical_lines(specs, frame, domain, tol, zone_names)
    state.lines = lines
    state.shared = shared
    cell_lines = [line for line in lines if specs[line.family].intent == "cell"]
    face_lines = [line for line in lines if specs[line.family].intent == "face"]
    place_chain_seeds(state, cell_lines)
    crossings = open_river_crossings(state, face_lines)
    build_face_graph(state, face_lines)
    locate_shared_segments(state)
    place_mirror_seeds(state)
    join_crossing_pairs(state, crossings)
    resolve_conflicts(state)
    place_boundary_seeds(state, step=h.h_min / 4.0, pixel=_pixel(request))
    resolve_conflicts(state)
    return _assemble(state, specs, zone_names, notes)


def _pixel(request: MeshRequest) -> float:
    """The DEM pixel size [m], the tolerance of the corner detection."""
    return max(request.grid.dx, request.grid.dy)


def _assemble(
    state: ConstraintState,
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
    segment_seeds = np.where(
        state.segment_seeds >= 0, final[np.maximum(state.segment_seeds, 0)], -1
    )
    pair_id = np.full(order.size, -1, dtype=np.int64)
    for side in (1, 0):
        has = segment_seeds[:, side] >= 0
        segments = np.flatnonzero(has)[::-1]
        pair_id[segment_seeds[segments, side]] = segments
    vertex_id = np.where(
        np.isin(seeds.role[order], (SeedRole.FREE_END, SeedRole.BOUNDARY)), seeds.vertex[order], -1
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
    conformal_vertex[conformal_vertices(state)] = True
    by_gid = {line.gid: line for line in state.lines}
    faces = FaceLineState(
        vertices=state.vertices,
        radius=state.radius,
        conformal=conformal_vertex,
        segment_nodes=state.seg_nodes,
        segment_seeds=segment_seeds,
        segment_conformal=state.conformal.copy(),
        segment_family=state.seg_family,
        segment_line=state.seg_line,
        zone_left=np.asarray(
            [by_gid[g].zone_left for g in state.seg_line.tolist()], dtype=np.int32
        ),
        zone_right=np.asarray(
            [by_gid[g].zone_right for g in state.seg_line.tolist()], dtype=np.int32
        ),
        shared_segment=state.shared_segment,
        shared_family=state.shared_family,
        shared_reversed=state.shared_reversed,
    )
    chains = _cell_chains(state, specs, final, order)
    return ConstraintPlan(
        seeds=constraint,
        faces=faces,
        chains=chains,
        family_names=state.family_names,
        zone_names=zone_names,
        source_lines=_source_lines(state, specs),
        family_stats=_family_stats(state, constraint, faces, specs),
        notes=notes,
    )


def _cell_chains(
    state: ConstraintState, specs: Sequence[LineFamilySpec], final: np.ndarray, order: np.ndarray
) -> tuple[CellChain, ...]:
    """Each river chain on the final seed ids, with the lateral offset of each cell."""
    chains = []
    for rank, chain in enumerate(state.chains):
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
        chains.append(
            CellChain(
                family=specs[chain.line.family].name,
                chain_id=rank,
                cell_ids=ids,
                offset_m=offset,
            )
        )
    return tuple(chains)


def _source_lines(
    state: ConstraintState, specs: Sequence[LineFamilySpec]
) -> dict[str, tuple[LineString, ...]]:
    """The lines each family was meshed on, local frame (face lines without the crossings)."""
    out: dict[str, list[LineString]] = {spec.name: [] for spec in specs}
    for chain in state.chains:
        out[specs[chain.line.family].name].append(LineString(chain.line.coords))
    for line in state.lines:
        if specs[line.family].intent == "face":
            out[specs[line.family].name].append(LineString(line.source))
    for stretch in state.shared:
        out[specs[stretch.family].name].append(LineString(stretch.coords))
    return {name: tuple(lines) for name, lines in out.items()}


def _family_stats(
    state: ConstraintState,
    seeds: ConstraintSeeds,
    faces: FaceLineState,
    specs: Sequence[LineFamilySpec],
) -> dict[str, dict[str, float]]:
    """The QA numbers of each family that the constraint stage knows."""
    stats: dict[str, dict[str, float]] = {}
    open_end = state.degree() == 1
    open_end[state.end_vertices] = False
    open_end &= state.free_end_seed < 0
    for index, spec in enumerate(specs):
        if spec.intent == "cell":
            crossings = [
                c
                for c in state.crossings
                if c.active and state.chains[c.chain].line.family == index
            ]
            offsets = np.asarray(
                [
                    shapely.distance(
                        shapely.points(state.seeds.xy[state.segment_seeds[c.segment]]),
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
        mine[state.shared_segment[state.shared_family == index]] = True
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
            "merged_circles": float(np.count_nonzero(mine & (state.reason == LOST_BY_MERGE))),
            "shrunk_circles": float(np.count_nonzero(touched & state.shrunk)),
            "free_ends": float(
                np.count_nonzero((seeds.role == SeedRole.FREE_END) & (seeds.family == index))
            ),
            "boundary_ends": float(
                np.count_nonzero((seeds.role == SeedRole.BOUNDARY) & (seeds.family == index)) // 2
            ),
            "yielded_segments": float(np.count_nonzero(mine & (state.reason == LOST_BY_CONFLICT))),
        }
    return stats

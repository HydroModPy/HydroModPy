"""Blocking gates of the Voronoi generator.

A gate that fails stops the build with ``MeshGenerationError``; it is never a
warning. The message lists at most 20 faulty elements, in Lambert-93, and the
total of each gate.

- G0: one cell per seed, each of positive area, each covering its seed.
- G1: Berge definition 2: no seed inside the ball of a conformal vertex but
  the seeds of its own sphere.
- G2: each conformal segment is the face shared by the cells of its pair, its
  two nodes within 1 mm of the segment ends.
- G3: two distinct consecutive cells of a chain are neighbours.
- G4: the cell areas add up to the domain area at 1e-9.
- G5: no vertex repeated in a cell, at least three per cell.
- G6: no face shorter than 1e-6 m.

G1 and G2 read the constraint plan of a generated mesh. A segment that is
not conformal (a merged sector, a crossing, a yielded contact) is not a
fault: G1 and G2 never check it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely
from scipy.spatial import cKDTree

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.constraints.plan import ConstraintPlan, FaceLineState
from hydromodpy.spatial.mesh.engines.voronoi.constraints.state import CIRCLE_SHRINK
from hydromodpy.spatial.mesh.engines.voronoi.local_coords import LocalFrame
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import MAX_LISTED
from hydromodpy.spatial.mesh.model.geometry import DerivedGeometry, derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain
from hydromodpy.spatial.mesh.model.quality import DEGENERATE_FACE_M

__all__ = [
    "AREA_GATE_REL",
    "FACE_ON_LINE_M",
    "SEED_COVER_M",
    "GateReport",
    "check_gates",
    "gated_geometry",
    "mirror_face_runs",
]

AREA_GATE_REL = 1.0e-9
"""G4: largest relative gap between the cell area sum and the domain area."""

FACE_ON_LINE_M = 1.0e-3
"""G2: largest distance [m] between a face node and its segment end."""

SEED_COVER_M = 1.0e-6
"""G0: largest distance [m] between a seed and its clipped cell (a seed on the boundary)."""


@dataclass(frozen=True, eq=False)
class GateReport:
    """What the gates checked, all passed."""

    n_cells: int
    area_rel_error: float
    def2_vertices: int
    mirror_faces: int
    chain_links: int
    face_rows: np.ndarray = field(repr=False)

    def extras(self) -> dict[str, float]:
        """The gate counts of the mesh QA."""
        return {
            "gate_def2_vertices": float(self.def2_vertices),
            "gate_mirror_faces": float(self.mirror_faces),
            "gate_chain_links": float(self.chain_links),
        }


def gated_geometry(mesh: HydroMesh) -> DerivedGeometry:
    """The derived geometry, a topology error (an edge of three cells) raised as a gate."""
    try:
        return derive_geometry(mesh)
    except ValueError as error:
        raise MeshGenerationError(f"gate G5: {error}") from error


def check_gates(
    *,
    seeds: np.ndarray,
    cells: np.ndarray,
    vertices: np.ndarray,
    geometry: DerivedGeometry,
    domain_area: float,
    frame: LocalFrame,
    chains: Sequence[CellChain] = (),
    plan: ConstraintPlan | None = None,
) -> GateReport:
    """Run G0 to G6 and raise ``MeshGenerationError`` naming the faults of every failed gate.

    *seeds*, the clipped *cells* and the mesh *vertices* are in the local
    frame; *geometry* is derived from the mesh. G1 and G2 run on the
    constraint *plan* of a generated mesh; without one they check nothing.
    ``face_rows`` of the report holds, for each face of
    :func:`mirror_face_runs`, the edge row of that face in *geometry*.
    """
    points = np.asarray(seeds, dtype=np.float64).reshape(-1, 2)
    xy = np.asarray(vertices, dtype=np.float64).reshape(-1, 2)
    faults: list[tuple[str, int, list[str]]] = []
    faults.append(_g0(points, np.asarray(cells), geometry, frame))
    face_rows = np.empty(0, dtype=np.int64)
    def2_vertices = 0
    if plan is not None:
        fault, def2_vertices = _g1(points, plan, frame)
        faults.append(fault)
        fault, face_rows = _g2(plan, xy, geometry, frame)
        faults.append(fault)
    fault, links = _g3(chains, geometry, points, frame)
    faults.append(fault)
    area_rel = abs(float(geometry.areas.sum()) - domain_area) / domain_area
    faults.append(
        (
            "G4",
            int(area_rel > AREA_GATE_REL),
            [_area_fault(float(geometry.areas.sum()), domain_area)]
            if area_rel > AREA_GATE_REL
            else [],
        )
    )
    faults.append(_g5(geometry, points, frame))
    faults.append(_g6(geometry, xy, frame))
    failed = [(gate, total, listed) for gate, total, listed in faults if total]
    if failed:
        totals = ", ".join(f"{gate}: {total}" for gate, total, _ in failed)
        named = [f"{gate} {item}" for gate, _, listed in failed for item in listed][:MAX_LISTED]
        raise MeshGenerationError(
            f"Voronoi gates failed ({totals}); first faults: " + "; ".join(named)
        )
    return GateReport(
        n_cells=geometry.n_cells,
        area_rel_error=area_rel,
        def2_vertices=def2_vertices,
        mirror_faces=0 if plan is None else len(face_rows),
        chain_links=links,
        face_rows=face_rows,
    )


def _area_fault(cells_area: float, domain_area: float) -> str:
    """The G4 fault; a missing area usually comes from a ring of the domain touching another."""
    fault = f"cell areas add up to {cells_area:.6f} m2 for {domain_area:.6f} m2"
    if cells_area < domain_area:
        fault += " (a hole touching another ring of the domain at one point leaves a sliver)"
    return fault


def _at(frame: LocalFrame, xy: np.ndarray) -> str:
    """Lambert-93 coordinates of one local point, for a message."""
    x, y = frame.to_world(np.reshape(xy, (1, 2)))[0]
    return f"({x:.3f}, {y:.3f})"


def _g0(
    seeds: np.ndarray, cells: np.ndarray, geometry: DerivedGeometry, frame: LocalFrame
) -> tuple[str, int, list[str]]:
    """One cell per seed, of positive area, covering its seed."""
    if geometry.n_cells != len(seeds) or len(cells) != len(seeds):
        return (
            "G0",
            1,
            [
                f"{geometry.n_cells} mesh cells and {len(cells)} clipped cells for {len(seeds)} seeds"
            ],
        )
    flat = geometry.areas <= 0.0
    far = ~shapely.dwithin(cells, shapely.points(seeds), SEED_COVER_M)
    bad = np.flatnonzero(flat | far)
    listed = [
        f"seed {int(i)} at {_at(frame, seeds[i])}: "
        + ("cell of zero area" if flat[i] else "outside its cell")
        for i in bad[:MAX_LISTED]
    ]
    return "G0", int(bad.size), listed


def _g1(
    seeds: np.ndarray, plan: ConstraintPlan, frame: LocalFrame
) -> tuple[tuple[str, int, list[str]], int]:
    """No seed but its own sphere seeds in the open ball of each conformal vertex.

    Return the fault and the number of vertices checked.
    """
    faces = plan.faces
    vertices = np.flatnonzero(faces.conformal)
    if not vertices.size:
        return ("G1", 0, []), 0
    owner, members = _sphere_members(plan, vertices)
    family, line = _first_line_of_vertices(faces)
    center = faces.vertices[vertices]
    tree = cKDTree(seeds)
    radius = faces.radius[vertices] * (1.0 - CIRCLE_SHRINK)
    found = np.asarray(tree.query_ball_point(center, radius, return_length=True))
    near = np.hypot(*(seeds[members] - center[owner]).T) < radius[owner]
    allowed = np.bincount(owner, weights=near, minlength=len(radius)).astype(np.int64)
    bad = np.flatnonzero(found > allowed)
    listed = []
    for i in bad[:MAX_LISTED].tolist():
        own = set(members[owner == i].tolist())
        intruders = [j for j in tree.query_ball_point(center[i], radius[i]) if j not in own]
        vertex = vertices[i]
        listed.append(
            f"family {plan.family_names[family[vertex]]!r} line {int(line[vertex])} vertex "
            f"{int(vertex)} at {_at(frame, center[i])}, ball radius "
            f"{faces.radius[vertex]:.3f} m: seed(s) "
            + ", ".join(f"{j} at {_at(frame, seeds[j])}" for j in sorted(intruders))
        )
    return ("G1", int(bad.size), listed), int(vertices.size)


def _sphere_members(plan: ConstraintPlan, vertices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rank in *vertices* and seed id of each seed allowed on the sphere of a conformal vertex.

    These are the pairs of its segments and its tip or boundary end seeds,
    each listed once, sorted by vertex then seed.
    """
    faces = plan.faces
    rank = np.full(len(faces.vertices), -1, dtype=np.int64)
    rank[vertices] = np.arange(vertices.size)
    node = faces.segment_nodes.T.ravel()
    segment = np.tile(np.arange(len(faces.segment_nodes)), 2)
    sphere = np.flatnonzero(plan.seeds.vertex_id >= 0)
    owner = np.concatenate([np.repeat(node, 2), plan.seeds.vertex_id[sphere]])
    member = np.concatenate([faces.segment_seeds[segment].ravel(), sphere])
    keep = (member >= 0) & (rank[owner] >= 0)
    pairs = np.unique(np.column_stack([rank[owner[keep]], member[keep]]), axis=0)
    return pairs[:, 0], pairs[:, 1]


def _first_line_of_vertices(faces: FaceLineState) -> tuple[np.ndarray, np.ndarray]:
    """Family and line of each face vertex, from its segment of the lowest line id."""
    node = faces.segment_nodes.T.ravel()
    segment = np.tile(np.arange(len(faces.segment_nodes)), 2)
    primary = np.lexsort((faces.segment_line[segment], node))
    first = primary[np.unique(node[primary], return_index=True)[1]]
    family = np.full(len(faces.vertices), -1, dtype=np.int64)
    line = np.full(len(faces.vertices), -1, dtype=np.int64)
    family[node[first]] = faces.segment_family[segment[first]]
    line[node[first]] = faces.segment_line[segment[first]]
    return family, line


def mirror_face_runs(faces: FaceLineState) -> np.ndarray:
    """First and last segment ``(k, 2)`` of each face of a conformal pair (gate G2).

    A run of segments that share one pair (a straight vertex whose two
    sectors share their seeds has only those two seeds on its sphere) is
    one face from the start of the run to its end. A face is kept when both
    its ends are conformal vertices.
    """
    nodes = faces.segment_nodes
    runs = _pair_runs(faces)
    keep = faces.conformal[nodes[runs[:, 0], 0]] & faces.conformal[nodes[runs[:, 1], 1]]
    return runs[keep]


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


def _g2(
    plan: ConstraintPlan, vertices: np.ndarray, geometry: DerivedGeometry, frame: LocalFrame
) -> tuple[tuple[str, int, list[str]], np.ndarray]:
    """The face of each pair exists and lies on its segment; return its edge rows."""
    faces = plan.faces
    runs = mirror_face_runs(faces)
    rows = np.full(len(runs), -1, dtype=np.int64)
    if not len(rows):
        return ("G2", 0, []), rows
    first = runs[:, 0]
    plus, minus = faces.segment_seeds[first, 0], faces.segment_seeds[first, 1]
    start = faces.vertices[faces.segment_nodes[first, 0]]
    end = faces.vertices[faces.segment_nodes[runs[:, 1], 1]]
    edge = geometry.edge_between(plus, minus)
    exists = edge >= 0
    nodes = vertices[geometry.edge_nodes[np.maximum(edge, 0)]]
    gap = np.minimum(
        np.maximum(_dist(nodes[:, 0], start), _dist(nodes[:, 1], end)),
        np.maximum(_dist(nodes[:, 0], end), _dist(nodes[:, 1], start)),
    )
    on_line = exists & (gap <= FACE_ON_LINE_M)
    rows[on_line] = edge[on_line]
    bad = np.flatnonzero(~on_line)
    listed = [
        f"family {plan.family_names[faces.segment_family[first[i]]]!r} line "
        f"{int(faces.segment_line[first[i]])} segment {int(first[i])} from "
        f"{_at(frame, start[i])} to {_at(frame, end[i])}: "
        + (
            f"face of seeds {int(plus[i])} and {int(minus[i])} is {gap[i]:.2e} m off the segment"
            if exists[i]
            else f"seeds {int(plus[i])} and {int(minus[i])} share no face"
        )
        for i in bad[:MAX_LISTED].tolist()
    ]
    return ("G2", int(bad.size), listed), rows


def _g3(
    chains: Sequence[CellChain], geometry: DerivedGeometry, seeds: np.ndarray, frame: LocalFrame
) -> tuple[tuple[str, int, list[str]], int]:
    """Two distinct consecutive cells of each chain are neighbours; return the links checked."""
    if not chains:
        return ("G3", 0, []), 0
    starts = np.concatenate([chain.cell_ids[:-1] for chain in chains])
    stops = np.concatenate([chain.cell_ids[1:] for chain in chains])
    chain_of = np.concatenate(
        [np.full(max(len(chain.cell_ids) - 1, 0), k) for k, chain in enumerate(chains)]
    )
    link = starts != stops
    starts, stops, chain_of = starts[link], stops[link], chain_of[link]
    linked = geometry.edge_between(starts, stops) >= 0
    bad = np.flatnonzero(~linked)
    listed = [
        f"chain {chains[chain_of[i]].family!r} {chains[chain_of[i]].chain_id}: cells "
        f"{int(starts[i])} at {_at(frame, seeds[starts[i]])} and {int(stops[i])} at "
        f"{_at(frame, seeds[stops[i]])} are not neighbours"
        for i in bad[:MAX_LISTED].tolist()
    ]
    return ("G3", int(bad.size), listed), int(len(starts))


def _g5(
    geometry: DerivedGeometry, seeds: np.ndarray, frame: LocalFrame
) -> tuple[str, int, list[str]]:
    """No repeated vertex in a cell, at least three vertices per cell."""
    rows = np.asarray(geometry.padded_connectivity, dtype=np.int64)
    corners = (rows >= 0).sum(axis=1)
    ordered = np.sort(np.where(rows >= 0, rows, -1 - np.arange(rows.shape[1])), axis=1)
    repeated = np.any((ordered[:, 1:] == ordered[:, :-1]) & (ordered[:, 1:] >= 0), axis=1)
    bad = np.flatnonzero(repeated | (corners < 3))
    listed = [
        f"cell {int(i)} at {_at(frame, seeds[i])}: "
        + ("a vertex repeats" if repeated[i] else f"{int(corners[i])} vertices")
        for i in bad[:MAX_LISTED].tolist()
    ]
    return "G5", int(bad.size), listed


def _g6(
    geometry: DerivedGeometry, vertices: np.ndarray, frame: LocalFrame
) -> tuple[str, int, list[str]]:
    """No face shorter than :data:`DEGENERATE_FACE_M`."""
    bad = np.flatnonzero(geometry.edge_length < DEGENERATE_FACE_M)
    listed = [
        f"face of cells {geometry.edge_cells[i].tolist()} at "
        f"{_at(frame, vertices[geometry.edge_nodes[i, 0]])}: {geometry.edge_length[i]:.2e} m"
        for i in bad[:MAX_LISTED].tolist()
    ]
    return "G6", int(bad.size), listed


def _dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise distance between two ``(n, 2)`` arrays."""
    return np.hypot(*(a - b).T)

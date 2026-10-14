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

A segment that is not conformal (a merged sector, a crossing, a yielded
contact) is not a fault: it is never handed to G1 or G2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import shapely
from scipy.spatial import cKDTree

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import MAX_LISTED
from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry, derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh
from hydromodpy.spatial.mesh.model.mesh_qa import DEGENERATE_FACE_M
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain

__all__ = [
    "AREA_GATE_REL",
    "BALL_SHRINK",
    "FACE_ON_LINE_M",
    "SEED_COVER_M",
    "BergeBalls",
    "GateReport",
    "MirrorFaces",
    "check_gates",
    "gated_geometry",
]

AREA_GATE_REL = 1.0e-9
"""G4: largest relative gap between the cell area sum and the domain area."""

BALL_SHRINK = 1.0e-9
"""G1 tests the open ball of radius ``R_v (1 - BALL_SHRINK)``: the sphere seeds lie on its edge."""

FACE_ON_LINE_M = 1.0e-3
"""G2: largest distance [m] between a face node and its segment end."""

SEED_COVER_M = 1.0e-6
"""G0: largest distance [m] between a seed and its clipped cell (a seed on the boundary)."""


@dataclass(frozen=True, eq=False)
class BergeBalls:
    """The conformal vertices of the face lines and the seeds allowed in each ball (G1).

    ``members`` holds, for vertex ``i``, the seed ids
    ``members[indptr[i]:indptr[i + 1]]``: the pairs of its segments, its tip or
    boundary end seeds, a shared sector seed. ``family`` indexes ``names``.
    """

    center: np.ndarray
    radius: np.ndarray
    indptr: np.ndarray
    members: np.ndarray
    family: np.ndarray
    line_id: np.ndarray
    vertex_id: np.ndarray
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        """Check the shapes."""
        n = len(np.asarray(self.radius).ravel())
        _set(self, "center", np.asarray(self.center, dtype=np.float64).reshape(-1, 2), n)
        _set(self, "radius", np.asarray(self.radius, dtype=np.float64).ravel(), n)
        _set(self, "family", np.asarray(self.family, dtype=np.int64).ravel(), n)
        _set(self, "line_id", np.asarray(self.line_id, dtype=np.int64).ravel(), n)
        _set(self, "vertex_id", np.asarray(self.vertex_id, dtype=np.int64).ravel(), n)
        _set(self, "indptr", np.asarray(self.indptr, dtype=np.int64).ravel(), n + 1)
        object.__setattr__(self, "members", np.asarray(self.members, dtype=np.int64).ravel())
        if self.indptr[0] != 0 or self.indptr[-1] != self.members.size:
            raise ValueError("BergeBalls.indptr does not span members")


@dataclass(frozen=True, eq=False)
class MirrorFaces:
    """The conformal segments ``[start, end]`` and the seeds of their pair (G2).

    ``plus`` is the seed on the left of the oriented segment, ``minus`` the one
    on its right; seed ids are cell ids.
    """

    plus: np.ndarray
    minus: np.ndarray
    start: np.ndarray
    end: np.ndarray
    family: np.ndarray
    line_id: np.ndarray
    segment_id: np.ndarray
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        """Check the shapes."""
        n = len(np.asarray(self.plus).ravel())
        _set(self, "plus", np.asarray(self.plus, dtype=np.int64).ravel(), n)
        _set(self, "minus", np.asarray(self.minus, dtype=np.int64).ravel(), n)
        _set(self, "start", np.asarray(self.start, dtype=np.float64).reshape(-1, 2), n)
        _set(self, "end", np.asarray(self.end, dtype=np.float64).reshape(-1, 2), n)
        _set(self, "family", np.asarray(self.family, dtype=np.int64).ravel(), n)
        _set(self, "line_id", np.asarray(self.line_id, dtype=np.int64).ravel(), n)
        _set(self, "segment_id", np.asarray(self.segment_id, dtype=np.int64).ravel(), n)


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
    balls: BergeBalls | None = None,
    faces: MirrorFaces | None = None,
) -> GateReport:
    """Run G0 to G6 and raise ``MeshGenerationError`` naming the faults of every failed gate.

    *seeds*, the clipped *cells* and the mesh *vertices* are in the local
    frame; *geometry* is derived from the mesh. ``face_rows`` of the report
    holds, for each conformal segment, the edge row of its face in *geometry*.
    """
    points = np.asarray(seeds, dtype=np.float64).reshape(-1, 2)
    xy = np.asarray(vertices, dtype=np.float64).reshape(-1, 2)
    faults: list[tuple[str, int, list[str]]] = []
    faults.append(_g0(points, np.asarray(cells), geometry, frame))
    if balls is not None:
        faults.append(_g1(points, balls, frame))
    face_rows = np.empty(0, dtype=np.int64)
    if faces is not None:
        fault, face_rows = _g2(faces, xy, geometry, frame)
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
        def2_vertices=0 if balls is None else len(balls.radius),
        mirror_faces=0 if faces is None else len(faces.plus),
        chain_links=links,
        face_rows=face_rows,
    )


def _area_fault(cells_area: float, domain_area: float) -> str:
    """The G4 fault; a missing area usually comes from a ring of the domain touching another."""
    fault = f"cell areas add up to {cells_area:.6f} m2 for {domain_area:.6f} m2"
    if cells_area < domain_area:
        fault += " (a hole touching another ring of the domain at one point leaves a sliver)"
    return fault


def _set(owner: object, name: str, value: np.ndarray, n: int) -> None:
    """Store *value* on the frozen *owner* after checking its length."""
    if len(value) != n:
        raise ValueError(f"{type(owner).__name__}.{name} needs {n} rows, got {len(value)}")
    object.__setattr__(owner, name, value)


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


def _g1(seeds: np.ndarray, balls: BergeBalls, frame: LocalFrame) -> tuple[str, int, list[str]]:
    """No seed but its own sphere seeds in the open ball of each conformal vertex."""
    if not len(balls.radius):
        return "G1", 0, []
    tree = cKDTree(seeds)
    radius = balls.radius * (1.0 - BALL_SHRINK)
    found = np.asarray(tree.query_ball_point(balls.center, radius, return_length=True))
    owner = np.repeat(np.arange(len(radius)), np.diff(balls.indptr))
    near = np.hypot(*(seeds[balls.members] - balls.center[owner]).T) < radius[owner]
    allowed = np.bincount(owner, weights=near, minlength=len(radius)).astype(np.int64)
    bad = np.flatnonzero(found > allowed)
    listed = []
    for i in bad[:MAX_LISTED].tolist():
        own = set(balls.members[balls.indptr[i] : balls.indptr[i + 1]].tolist())
        intruders = [j for j in tree.query_ball_point(balls.center[i], radius[i]) if j not in own]
        listed.append(
            f"family {balls.names[balls.family[i]]!r} line {int(balls.line_id[i])} vertex "
            f"{int(balls.vertex_id[i])} at {_at(frame, balls.center[i])}, ball radius "
            f"{balls.radius[i]:.3f} m: seed(s) "
            + ", ".join(f"{j} at {_at(frame, seeds[j])}" for j in sorted(intruders))
        )
    return "G1", int(bad.size), listed


def _g2(
    faces: MirrorFaces, vertices: np.ndarray, geometry: DerivedGeometry, frame: LocalFrame
) -> tuple[tuple[str, int, list[str]], np.ndarray]:
    """The face of each pair exists and lies on its segment; return its edge rows."""
    n = geometry.n_cells
    rows = np.full(len(faces.plus), -1, dtype=np.int64)
    if not len(rows):
        return ("G2", 0, []), rows
    lo = np.minimum(faces.plus, faces.minus)
    hi = np.maximum(faces.plus, faces.minus)
    probe = lo * np.int64(n) + hi
    edge_key = geometry.edge_cells[:, 0] * np.int64(n) + geometry.edge_cells[:, 1]
    interior = geometry.edge_cells[:, 1] >= 0
    order = np.flatnonzero(interior)[np.argsort(edge_key[interior], kind="stable")]
    sorted_key = edge_key[order]
    if len(order):
        position = np.minimum(np.searchsorted(sorted_key, probe), len(order) - 1)
        exists = (sorted_key[position] == probe) & (lo != hi)
        edge = order[position]
    else:
        exists = np.zeros(len(rows), dtype=bool)
        edge = np.zeros(len(rows), dtype=np.int64)
    nodes = vertices[geometry.edge_nodes[edge]]
    gap = np.minimum(
        np.maximum(_dist(nodes[:, 0], faces.start), _dist(nodes[:, 1], faces.end)),
        np.maximum(_dist(nodes[:, 0], faces.end), _dist(nodes[:, 1], faces.start)),
    )
    on_line = exists & (gap <= FACE_ON_LINE_M)
    rows[on_line] = edge[on_line]
    bad = np.flatnonzero(~on_line)
    listed = [
        f"family {faces.names[faces.family[i]]!r} line {int(faces.line_id[i])} segment "
        f"{int(faces.segment_id[i])} from {_at(frame, faces.start[i])} to "
        f"{_at(frame, faces.end[i])}: "
        + (
            f"face of seeds {int(faces.plus[i])} and {int(faces.minus[i])} is "
            f"{gap[i]:.2e} m off the segment"
            if exists[i]
            else f"seeds {int(faces.plus[i])} and {int(faces.minus[i])} share no face"
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
    n = geometry.n_cells
    starts = np.concatenate([chain.cell_ids[:-1] for chain in chains])
    stops = np.concatenate([chain.cell_ids[1:] for chain in chains])
    chain_of = np.concatenate(
        [np.full(max(len(chain.cell_ids) - 1, 0), k) for k, chain in enumerate(chains)]
    )
    link = starts != stops
    starts, stops, chain_of = starts[link], stops[link], chain_of[link]
    indptr, indices = geometry.adjacency_indptr, geometry.adjacency_indices
    adjacent = np.repeat(np.arange(n, dtype=np.int64), np.diff(indptr)) * np.int64(n) + indices
    adjacent.sort()
    probe = starts * np.int64(n) + stops
    position = np.minimum(np.searchsorted(adjacent, probe), max(len(adjacent) - 1, 0))
    linked = (adjacent[position] == probe) if len(adjacent) else np.zeros(len(probe), dtype=bool)
    bad = np.flatnonzero(~linked)
    listed = [
        f"chain {chains[chain_of[i]].family!r} {chains[chain_of[i]].chain_id}: cells "
        f"{int(starts[i])} at {_at(frame, seeds[starts[i]])} and {int(stops[i])} at "
        f"{_at(frame, seeds[stops[i]])} are not neighbours"
        for i in bad[:MAX_LISTED].tolist()
    ]
    return ("G3", int(bad.size), listed), int(len(probe))


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

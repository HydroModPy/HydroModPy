"""The Voronoi dual of a triangulation read from a file: its vertices are the generators.

No constraint seed and no relaxation: the refinement and the lines the triangles
follow are in the vertex placement. The cells are tessellated as in the
generated mode (``tessellation.py``, in the local frame); the families are
carried over from the triangles.

The generators are the vertices of the triangulation read, so the cell of
vertex ``v`` is cell ``v``; a cell past the last vertex is a boundary seed that
the tessellation added for a piece of the domain no vertex reaches. A river
runs through vertices, so its chain is the cells of those vertices; where the
dual of two consecutive vertices shares no face (a constrained edge that is not
Delaunay), the common neighbor closest to the line bridges them. A face family
line runs through vertices too, so no dual face lies on it: the family becomes
the staircase of dual faces between the cells of its two sides, each cell taking
the side most of the triangles around its vertex lie on. The river faces are the
dual faces a river edge crosses, and the box sides are the faces of the cells
centered on them.

The engine declares exact faces, which a staircase is not, and two readers take
that declaration at its word: the zone of a cell (``zone_fractions``) and the cells
of a lake (``resolve_lake_cells``). So a dual publishes no cell zone, and no
staircase for the lake shores: its zones and its lakes come from the support and
the polygon overlap, as they did before.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.mesh.cells.regions import components_without
from hydromodpy.mesh.engines.face_families import FamilyEdges, face_table
from hydromodpy.mesh.engines.triangle.engine import TriangulatedRequest, triangulate_request
from hydromodpy.mesh.engines.voronoi.checks import check_gates, gated_geometry
from hydromodpy.mesh.engines.voronoi.local_coords import local_frame
from hydromodpy.mesh.engines.voronoi.tessellation import (
    cell_topology,
    tessellate,
    voronoi_envelope,
)
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import (
    BOX_SIDES,
    DerivedGeometry,
    box_side_of_edges,
)
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import (
    CellChain,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.mesh.request import MeshRequest

__all__ = ["dual_chains", "dual_face_families", "river_faces", "side_faces", "dual_cell_mesh"]

RIVERS_FAMILY = "rivers"
"""The family whose faces the river edges cross, and whose cells form the chains."""

CENTRE_TOLERANCE_REL = 1.0e-6
"""A cell is centered on a side within this share of its size."""

CENTRE_TOLERANCE_ABS_M = 1.0e-9
"""Smallest distance [m] from a side that still counts as centered on it."""

UNSTAIRED_FAMILIES = ("lakes",)
"""Face families a dual does not publish as a staircase (see the module docstring)."""


def _bridged(cells: np.ndarray, geometry: DerivedGeometry, centers: np.ndarray) -> np.ndarray:
    """Bridge two chain cells without a shared face by their common neighbor nearest both."""
    out = [int(cells[0])]
    for nxt in cells[1:].tolist():
        last = out[-1]
        if nxt != last and nxt not in geometry.neighbours(last):
            common = np.intersect1d(geometry.neighbours(last), geometry.neighbours(nxt))
            if common.size:
                gap = np.hypot(*(centers[common] - centers[last]).T) + np.hypot(
                    *(centers[common] - centers[nxt]).T
                )
                out.append(int(common[np.argmin(gap)]))
        out.append(int(nxt))
    return np.asarray(out, dtype=np.int64)


def dual_chains(
    triangulated: TriangulatedRequest, geometry: DerivedGeometry, centers: np.ndarray
) -> tuple[CellChain, ...]:
    """One chain per line of each cell family: the dual cells of its vertices, in order."""
    chains: list[CellChain] = []
    for name in triangulated.families.cell_families:
        family = triangulated.families.get(name)
        if family is None:
            continue
        for line in np.unique(family.line[family.line >= 0]).tolist():
            cells = family.line_vertices(line)
            if cells.size == 0:
                continue
            cells = cells[np.concatenate([[True], cells[1:] != cells[:-1]])]
            chains.append(
                CellChain(
                    family=name,
                    chain_id=len(chains),
                    cell_ids=_bridged(cells, geometry, centers),
                )
            )
    return tuple(chains)


def _vertex_votes(
    triangulated: TriangulatedRequest, triangle_label: np.ndarray, n_labels: int
) -> np.ndarray:
    """Label of each vertex: the label of the largest area of triangles around it."""
    triangles = np.asarray(triangulated.mesh.flat_connectivity, dtype=np.int64)
    weights = np.zeros((triangulated.mesh.n_nodes, n_labels))
    known = triangle_label >= 0
    for corner in range(3):
        np.add.at(
            weights,
            (triangles[known, corner], triangle_label[known]),
            triangulated.geometry.areas[known],
        )
    return np.where(weights.sum(axis=1) > 0.0, weights.argmax(axis=1), -1)


def _staircase(
    family: FamilyEdges,
    triangulated: TriangulatedRequest,
    geometry: DerivedGeometry,
    vertices: np.ndarray,
) -> FamilyEdges | None:
    """Dual faces between the cells of the two sides of one face family, oriented on its rows."""
    component = components_without(triangulated.geometry, family.cell_a, family.cell_b)
    vertex_side = _vertex_votes(triangulated, component, int(component.max()) + 1)
    side = np.full(geometry.n_cells, -1, dtype=np.int64)
    side[: len(vertex_side)] = vertex_side
    pairs = geometry.edge_cells
    faces = np.flatnonzero(
        (pairs[:, 1] >= 0) & (side[pairs[:, 0]] != side[np.maximum(pairs[:, 1], 0)])
    )
    if faces.size == 0:
        return None

    tri_xy = np.asarray(triangulated.mesh.vertices, dtype=float)
    start, stop = tri_xy[family.node_a], tri_xy[family.node_b]
    segments = shapely.linestrings(np.stack([start, stop], axis=1))
    middle = geometry.edge_midpoint[faces]
    nearest = STRtree(segments).query_nearest(shapely.points(middle))
    _, first = np.unique(nearest[0], return_index=True)
    row = nearest[1][first]
    tangent = stop[row] - start[row]
    offset = geometry.area_centroids[pairs[faces, 0]] - middle
    # The first cell is on the left when it lies on the side of the row's left
    # triangle; a face between two other sides falls back to the geometry.
    left_side = component[family.cell_a[row]]
    first_left = np.where(
        (side[pairs[faces, 0]] == left_side) | (side[pairs[faces, 1]] == left_side),
        side[pairs[faces, 0]] == left_side,
        tangent[:, 0] * offset[:, 1] - tangent[:, 1] * offset[:, 0] > 0.0,
    )
    cell_a = np.where(first_left, pairs[faces, 0], pairs[faces, 1])
    cell_b = np.where(first_left, pairs[faces, 1], pairs[faces, 0])
    nodes = geometry.edge_nodes[faces]
    face = vertices[nodes[:, 1]] - vertices[nodes[:, 0]]
    reach = geometry.area_centroids[cell_a] - vertices[nodes[:, 0]]
    keep = face[:, 0] * reach[:, 1] - face[:, 1] * reach[:, 0] > 0.0
    return FamilyEdges(
        name=family.name,
        node_a=np.where(keep, nodes[:, 0], nodes[:, 1]),
        node_b=np.where(keep, nodes[:, 1], nodes[:, 0]),
        cell_a=cell_a,
        cell_b=cell_b,
        zone_left=family.zone_left[row],
        zone_right=family.zone_right[row],
        line=family.line[row],
        forward=family.forward[row],
    )


def dual_face_families(
    triangulated: TriangulatedRequest, geometry: DerivedGeometry, vertices: np.ndarray
) -> tuple[FamilyEdges, ...]:
    """The staircase of every face family of the triangulation but sides, cell and lake shores."""
    out = []
    for family in triangulated.families.families:
        if (
            family.name.startswith("boundary:")
            or family.name in triangulated.families.cell_families
            or family.name in UNSTAIRED_FAMILIES
        ):
            continue
        staircase = _staircase(family, triangulated, geometry, vertices)
        if staircase is not None:
            out.append(staircase)
    return tuple(out)


def _plain_rows(name: str, edges: np.ndarray, geometry: DerivedGeometry) -> FamilyEdges:
    """The dual faces ``edges`` (rows of the geometry) as family rows without zones."""
    unknown = np.full(edges.size, -1, dtype=np.int32)
    return FamilyEdges(
        name=name,
        node_a=geometry.edge_nodes[edges, 0],
        node_b=geometry.edge_nodes[edges, 1],
        cell_a=geometry.edge_cells[edges, 0],
        cell_b=geometry.edge_cells[edges, 1],
        zone_left=unknown,
        zone_right=unknown,
        line=np.full(edges.size, -1, dtype=np.int64),
        forward=np.ones(edges.size, dtype=bool),
    )


def river_faces(
    triangulated: TriangulatedRequest, geometry: DerivedGeometry, vertices: np.ndarray
) -> FamilyEdges | None:
    """The dual faces a river edge of the triangulation crosses, so the river cells touch them."""
    rivers = triangulated.families.get(RIVERS_FAMILY)
    if rivers is None or rivers.node_a.size == 0:
        return None
    generators = np.asarray(triangulated.mesh.vertices, dtype=float)
    river_edges = shapely.linestrings(
        np.stack([generators[rivers.node_a], generators[rivers.node_b]], axis=1)
    )
    faces = shapely.linestrings(
        np.stack([vertices[geometry.edge_nodes[:, 0]], vertices[geometry.edge_nodes[:, 1]]], axis=1)
    )
    edges = np.unique(STRtree(faces).query(river_edges, predicate="intersects")[1])
    return _plain_rows(RIVERS_FAMILY, edges, geometry) if edges.size else None


def side_faces(
    geometry: DerivedGeometry, vertices: np.ndarray, centers: np.ndarray
) -> tuple[FamilyEdges, ...]:
    """The families ``boundary:<side>``: boundary faces on a side of the vertex box.

    The side of a face is the one :func:`box_side_of_edges` gives it. A side
    that has cells centered on it keeps the faces of those cells only: a
    Dirichlet head belongs on the boundary, not half a cell inside.
    """
    outer = np.flatnonzero(geometry.edge_cells[:, 1] < 0)
    pairs = geometry.edge_nodes[outer]
    side_of_face = box_side_of_edges(vertices, pairs[:, 0], pairs[:, 1])
    low = vertices.min(axis=0)
    high = vertices.max(axis=0)
    size = np.sqrt(geometry.areas)
    centre_tolerance = np.maximum(CENTRE_TOLERANCE_ABS_M, CENTRE_TOLERANCE_REL * size)
    sides = {}
    for index, (side, axis, value) in enumerate(
        zip(BOX_SIDES, (0, 0, 1, 1), (low[0], high[0], low[1], high[1]), strict=True)
    ):
        on_side = side_of_face == index
        centred = np.abs(centers[:, axis] - value) <= centre_tolerance
        if centred.any():
            on_side &= centred[geometry.edge_cells[outer, 0]]
        if on_side.any():
            sides[side] = outer[on_side]
    return tuple(_plain_rows(f"boundary:{side}", sides[side], geometry) for side in sorted(sides))


_FACES_NOTE = (
    "voronoi dual faces do not follow the face family lines: a face family is the "
    "staircase of dual faces between its two sides, rivers faces are the dual faces "
    "a river edge crosses"
)


def dual_cell_mesh(
    request: MeshRequest,
    *,
    identity: MeshIdentity,
    declarations: Mapping[str, bool],
    notes: Sequence[str],
) -> PlanarCellMesh:
    """Tessellate the vertices of the triangulation of *request*; the gates raise on any fault.

    *notes* open the notes of the mesh QA.
    """
    triangulated = triangulate_request(request)
    frame = local_frame(request.domain)
    domain = shapely.normalize(frame.to_local(request.domain))
    shapely.prepare(domain)
    generators = np.asarray(triangulated.mesh.vertices, dtype=float)[:, :2]
    seeds = frame.to_local(generators)
    tess = tessellate(seeds, len(seeds), domain, voronoi_envelope(domain, request.nominal_size_m))
    topology = cell_topology(tess.cells, frame)
    # The generators come first and unmoved; the boundary seeds the tessellation added follow.
    centers = np.vstack([generators, frame.to_world(tess.seeds[len(generators) :])])
    mesh = HydroMesh(
        vertices=frame.to_world(topology.vertices),
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=topology.rings),),
    )
    geometry = gated_geometry(mesh)
    chains = dual_chains(triangulated, geometry, centers)
    check_gates(
        seeds=tess.seeds,
        cells=tess.cells,
        vertices=topology.vertices,
        geometry=geometry,
        domain_area=domain.area,
        frame=frame,
        chains=chains,
    )
    vertices = np.asarray(mesh.vertices, dtype=float)
    families = (
        river_faces(triangulated, geometry, vertices),
        *side_faces(geometry, vertices, centers),
        *dual_face_families(triangulated, geometry, vertices),
    )
    return build_planar_cell_mesh(
        mesh,
        centers,
        geometry=geometry,
        center_kind="generator",
        crs_wkt=request.crs_wkt,
        identity=identity,
        declarations=declarations,
        cell_chains=chains,
        face_families=face_table(tuple(family for family in families if family is not None)),
        zone_names=triangulated.families.zone_names,
        domain_area_m2=request.domain.area,
        lines=triangulated.lines_for_qa(),
        notes=(
            *notes,
            *triangulated.notes,
            "voronoi generators are the vertices of the input triangulation",
            _FACES_NOTE,
        ),
        extras={
            "boundary_seeds_added": float(tess.boundary_seeds_added),
            "origin_x": frame.origin[0],
            "origin_y": frame.origin[1],
        },
    )

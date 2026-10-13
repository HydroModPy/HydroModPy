"""Families of the Voronoi dual, carried over from its triangulation.

A dual cell is the cell of one triangulation vertex. A river runs through
vertices, so its chain is the cells of those vertices; where the dual of two
consecutive vertices shares no face (a constrained edge that is not Delaunay),
the common neighbour closest to the line bridges them. A face family line runs
through vertices too, so no dual face lies on it: the family becomes the
staircase of dual faces between the cells of its two sides, each cell taking
the side most of the triangles around its vertex lie on.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.engines.triangle.engine import TriangulatedRequest
from hydromodpy.spatial.mesh.engines.triangle.families import FamilyEdges, components_without
from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, FaceFamilyTable

__all__ = ["dual_cell_zones", "dual_chains", "dual_face_families", "merge_face_tables"]


def _bridged(cells: np.ndarray, geometry: DerivedGeometry, centers: np.ndarray) -> np.ndarray:
    """Bridge two chain cells without a shared face by their common neighbour nearest both."""
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
    triangulated: TriangulatedRequest,
    cell_of_vertex: np.ndarray,
    geometry: DerivedGeometry,
    centers: np.ndarray,
) -> tuple[CellChain, ...]:
    """One chain per line of each cell family: the dual cells of its vertices, in order."""
    chains: list[CellChain] = []
    for name in triangulated.families.cell_families:
        family = triangulated.families.get(name)
        if family is None:
            continue
        for line in np.unique(family.line[family.line >= 0]).tolist():
            cells = cell_of_vertex[family.line_vertices(line)]
            cells = cells[cells >= 0]
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


def dual_cell_zones(
    triangulated: TriangulatedRequest,
    triangle_zone: np.ndarray | None,
    cell_of_vertex: np.ndarray,
    n_cells: int,
) -> np.ndarray | None:
    """Zone of each dual cell: the zone of most of the triangle area around its generator."""
    if triangle_zone is None:
        return None
    vertex_zone = _vertex_votes(
        triangulated, triangle_zone, max(len(triangulated.families.zone_names), 1)
    )
    zones = np.full(n_cells, -1, dtype=np.int32)
    kept = cell_of_vertex >= 0
    zones[cell_of_vertex[kept]] = vertex_zone[kept]
    return zones


def _staircase(
    family: FamilyEdges,
    triangulated: TriangulatedRequest,
    cell_of_vertex: np.ndarray,
    geometry: DerivedGeometry,
    vertices: np.ndarray,
) -> FamilyEdges | None:
    """Dual faces between the cells of the two sides of one face family, oriented on its rows."""
    component = components_without(triangulated.geometry, family.cell_a, family.cell_b)
    vertex_side = _vertex_votes(triangulated, component, int(component.max()) + 1)
    side = np.full(geometry.n_cells, -1, dtype=np.int64)
    kept = cell_of_vertex >= 0
    side[cell_of_vertex[kept]] = vertex_side[kept]
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
    triangulated: TriangulatedRequest,
    cell_of_vertex: np.ndarray,
    geometry: DerivedGeometry,
    vertices: np.ndarray,
) -> tuple[FamilyEdges, ...]:
    """The staircase of every face family of the triangulation but sides and cell families."""
    out = []
    for family in triangulated.families.families:
        if family.name.startswith("boundary:") or family.name in (
            triangulated.families.cell_families
        ):
            continue
        staircase = _staircase(family, triangulated, cell_of_vertex, geometry, vertices)
        if staircase is not None:
            out.append(staircase)
    return tuple(out)


def merge_face_tables(
    table: FaceFamilyTable | None, families: tuple[FamilyEdges, ...]
) -> FaceFamilyTable | None:
    """Append the rows of *families* to *table* under their own names."""
    if not families:
        return table
    names = (table.names if table is not None else ()) + tuple(f.name for f in families)
    offset = len(names) - len(families)
    columns = ("cell_a", "cell_b", "node_a", "node_b", "zone_left", "zone_right")
    head = {c: getattr(table, c) if table is not None else np.empty(0) for c in columns}
    return FaceFamilyTable(
        names=names,
        family=np.concatenate(
            [table.family if table is not None else np.empty(0, np.int16)]
            + [np.full(f.cell_a.size, offset + i) for i, f in enumerate(families)]
        ),
        **{c: np.concatenate([head[c]] + [getattr(f, c) for f in families]) for c in columns},
    )

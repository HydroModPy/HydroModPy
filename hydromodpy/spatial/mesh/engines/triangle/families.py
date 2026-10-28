"""Line families of a triangulation: oriented face rows, chains and zones.

A family line lies on mesh edges. Each of its edges becomes one row with the
triangle on the left of the oriented line as ``cell_a`` and the triangle on the
right as ``cell_b`` (``-1`` on the domain boundary, where the row is flipped so
that ``cell_a`` is the cell). The edges come from the gmsh driver for a
generated triangulation; for a read one, from its physical line groups, else by
matching the mesh edges to the request lines.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.engines.face_families import (
    EdgeLookup,
    FamilyEdges,
    components_without,
    oriented_rows,
    request_zone_names,
    without_repeats,
)
from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest

__all__ = [
    "TriangleFamilies",
    "cell_zones",
    "chains_of",
    "families_from_line_edges",
    "families_from_matching",
    "matching_tolerance",
]


@dataclass(frozen=True, eq=False)
class TriangleFamilies:
    """Every family of one triangulation and the zone names its rows index."""

    families: tuple[FamilyEdges, ...]
    zone_names: tuple[str, ...]
    cell_families: tuple[str, ...]

    def get(self, name: str) -> FamilyEdges | None:
        """The family named *name*, or ``None``."""
        return next((family for family in self.families if family.name == name), None)


def _zone_indices(
    family: LineFamilySpec, zone_names: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray]:
    """Zone index of each line of a family on its left and right, ``-1`` without zones."""
    if not family.zone_left:
        unknown = np.full(len(family.lines), -1, dtype=np.int32)
        return unknown, unknown
    index = {name: position for position, name in enumerate(zone_names)}
    return (
        np.asarray([index[zone] for zone in family.zone_left], dtype=np.int32),
        np.asarray([index[zone] for zone in family.zone_right], dtype=np.int32),
    )


def families_from_line_edges(
    request: MeshRequest,
    lookup: EdgeLookup,
    line_edges: Mapping[tuple[str, int], np.ndarray],
) -> TriangleFamilies:
    """Families of a generated triangulation, from the mesh edges of each line."""
    zone_names = request_zone_names(request)
    families = []
    for family in request.lines:
        left, right = _zone_indices(family, zone_names)
        edges = [np.asarray(line_edges[(family.name, i)]) for i in range(len(family.lines))]
        counts = [len(part) for part in edges]
        line = np.repeat(np.arange(len(edges)), counts)
        families.append(
            oriented_rows(family.name, lookup, np.concatenate(edges), line, left[line], right[line])
        )
    return TriangleFamilies(
        families=tuple(families),
        zone_names=zone_names,
        cell_families=tuple(f.name for f in request.lines if f.intent == "cell"),
    )


def matching_tolerance(vertices: np.ndarray) -> float:
    """Distance [m] within which an edge lies on a line: 1e-8 of the extent, 0.1 mm at least."""
    extent = float(np.ptp(vertices, axis=0).max())
    return max(1.0e-8 * extent, 1.0e-4)


def _matched_family(
    family: LineFamilySpec,
    vertices: np.ndarray,
    geometry: DerivedGeometry,
    lookup: EdgeLookup,
    zone_names: tuple[str, ...],
) -> FamilyEdges:
    """Rows of the mesh edges whose ends and middle lie on a line of *family*."""
    tolerance = matching_tolerance(vertices)
    lines = np.asarray(family.lines, dtype=object)
    tree = STRtree(lines)
    start = shapely.points(vertices[geometry.edge_nodes[:, 0]])
    stop = shapely.points(vertices[geometry.edge_nodes[:, 1]])
    middle = shapely.points(geometry.edge_midpoint)
    on_line = np.ones(len(geometry.edge_nodes), dtype=bool)
    for points in (start, middle, stop):
        near = np.zeros(on_line.size, dtype=bool)
        near[tree.query(points, predicate="dwithin", distance=tolerance)[0]] = True
        on_line &= near
    edges = np.flatnonzero(on_line)
    nearest = tree.query_nearest(middle[edges])
    _, first = np.unique(nearest[0], return_index=True)
    line = nearest[1][first].astype(np.int64)
    s_start = shapely.line_locate_point(lines[line], start[edges])
    s_stop = shapely.line_locate_point(lines[line], stop[edges])
    pairs = geometry.edge_nodes[edges]
    pairs = np.where((s_stop < s_start)[:, None], pairs[:, ::-1], pairs)
    order = np.lexsort((0.5 * (s_start + s_stop), line))
    left, right = _zone_indices(family, zone_names)
    line = line[order]
    return oriented_rows(family.name, lookup, pairs[order], line, left[line], right[line])


def families_from_matching(
    request: MeshRequest,
    vertices: np.ndarray,
    geometry: DerivedGeometry,
    lookup: EdgeLookup,
    *,
    skip: frozenset[str] = frozenset(),
) -> tuple[FamilyEdges, ...]:
    """Families of a read triangulation, by matching its edges to the request lines."""
    zone_names = request_zone_names(request)
    return tuple(
        _matched_family(family, vertices, geometry, lookup, zone_names)
        for family in request.lines
        if family.name not in skip
    )


def chains_of(family: FamilyEdges, lookup: EdgeLookup) -> tuple[CellChain, ...]:
    """One chain per line: the triangles on its left bank, in order, stepping by faces.

    Between the triangles left of two consecutive edges, the triangles around
    their shared vertex on the same bank are inserted, so two neighbours of a
    chain share a face.
    """
    chains = []
    for line in np.unique(family.line[family.line >= 0]).tolist():
        rows = np.flatnonzero(family.line == line)
        cells = [int(family.cell_a[rows[0]])]
        for before, after in zip(rows[:-1].tolist(), rows[1:].tolist(), strict=True):
            pivot = int(family.node_b[before])
            if family.forward[before] and family.forward[after] and pivot == family.node_a[after]:
                cells.extend(lookup.fan(cells[-1], pivot, int(family.node_b[after])))
            cells.append(int(family.cell_a[after]))
        chains.append(
            CellChain(family=family.name, chain_id=len(chains), cell_ids=without_repeats(cells))
        )
    return tuple(chains)


def cell_zones(
    geometry: DerivedGeometry, geology: FamilyEdges | None, n_zones: int
) -> np.ndarray | None:
    """Zone of each cell: the zone its component of cells between contacts borders most."""
    if geology is None or n_zones == 0 or geology.cell_a.size == 0:
        return None
    component = components_without(geometry, geology.cell_a, geology.cell_b)
    n_components = int(component.max()) + 1
    inside = geology.cell_b >= 0
    side_component = np.concatenate([component[geology.cell_a], component[geology.cell_b[inside]]])
    side_zone = np.concatenate([geology.zone_left, geology.zone_right[inside]])
    known = side_zone >= 0
    votes = np.zeros((n_components, n_zones), dtype=np.int64)
    np.add.at(votes, (side_component[known], side_zone[known]), 1)
    zone_of = np.where(votes.sum(axis=1) > 0, votes.argmax(axis=1), -1)
    return zone_of[component].astype(np.int32)

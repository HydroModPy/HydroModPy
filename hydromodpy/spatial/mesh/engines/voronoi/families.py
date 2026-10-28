"""Families of a generated Voronoi mesh: river chains, family faces, sides, zones.

Cell ``i`` is the cell of seed ``i``, and the constraint seeds come first, so
the plan of the constraint stage names its cells directly. A river chain is
the cells of its seeds; the face of a mirror pair is the mesh edge between
the cells of its two seeds; the boundary edges on the sides of the vertex box
are the families ``boundary:<side>``. The zone of a cell comes from the
geology pairs and spreads through the cells until a geology face stops it.
Coordinates are in the local frame of the generator.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.cells.regions import components_without
from hydromodpy.spatial.mesh.engines.voronoi.constraints.plan import ConstraintPlan, FaceLineState
from hydromodpy.spatial.mesh.model.geometry import (
    BOX_SIDES,
    DerivedGeometry,
    box_side_of_edges,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import FaceFamilyTable
from hydromodpy.spatial.mesh.model.quality import RELATIVE_FACE_TOLERANCE, mixed_cells

__all__ = ["GEOLOGY_FAMILY", "cell_zones", "face_family_table"]

GEOLOGY_FAMILY = "geology"
"""The face family whose two sides carry the zones of the cells."""


def face_family_table(
    plan: ConstraintPlan, geometry: DerivedGeometry, vertices: np.ndarray
) -> FaceFamilyTable | None:
    """The faces of the mirror pairs and of the box sides, one row per mesh edge.

    A row of a face family is the edge between the cells of the pair of a
    conformal segment, ``cell_a`` (the ``plus`` seed) on the left of the line,
    its nodes in the order of the line. A conformal segment next to a yielded
    vertex whose pair shares no edge has no row; the QA coverage shows it. A
    segment shared by a second family gives that family a row too, oriented
    along its own line.
    """
    families: list[tuple[str, dict[str, np.ndarray]]] = []
    segments, cells, nodes, edges = _mirror_faces(plan, geometry, vertices)
    faces = plan.faces
    for index, name in enumerate(plan.family_names):
        own = _first_per_edge(np.flatnonzero(faces.segment_family[segments] == index), edges)
        shared, flip = _shared_rows(faces, index, segments, edges, own)
        if not own.size and not shared.size:
            continue
        rows = np.concatenate([own, shared])
        flip = np.concatenate([np.zeros(own.size, dtype=bool), flip])[:, None]
        zones = np.column_stack([faces.zone_left[segments[rows]], faces.zone_right[segments[rows]]])
        zones[own.size :] = -1
        pair = np.where(flip, cells[rows][:, ::-1], cells[rows])
        ends = np.where(flip, nodes[rows][:, ::-1], nodes[rows])
        families.append(
            (
                name,
                {
                    "cell_a": pair[:, 0],
                    "cell_b": pair[:, 1],
                    "node_a": ends[:, 0],
                    "node_b": ends[:, 1],
                    "zone_left": zones[:, 0],
                    "zone_right": zones[:, 1],
                },
            )
        )
    families.extend(_side_faces(geometry, vertices))
    return FaceFamilyTable.stack(families) if families else None


def cell_zones(
    plan: ConstraintPlan,
    geometry: DerivedGeometry,
    vertices: np.ndarray,
    table: FaceFamilyTable | None,
) -> np.ndarray | None:
    """Zone of each cell from the geology pairs, ``-1`` where it is not one zone.

    The cells of a geology pair take the zone of their side. The other cells
    joined to them without crossing a geology face share that zone when the
    group they form meets one zone only; a group that meets two (a contact
    with a free end) is left at ``-1``. A yielded contact segment has no pair
    face, so the groups are also cut at every cell it crosses (a mixed cell)
    and at every edge it touches: the cells away from it keep their zone. A
    pair cell given two zones, and every mixed cell, is ``-1``. ``None`` when
    no geology face family carries zones.
    """
    if table is None or GEOLOGY_FAMILY not in table.names or not plan.zone_names:
        return None
    rows = table.family == table.names.index(GEOLOGY_FAMILY)
    cell_a, cell_b = table.cell_a[rows], table.cell_b[rows]
    inside = cell_b >= 0
    cell = np.concatenate([cell_a, cell_b[inside]])
    label = np.concatenate([table.zone_left[rows], table.zone_right[rows][inside]])
    known = label >= 0
    mixed = _mixed_cells(plan, geometry, vertices)
    cut = geometry.edge_cells[_lost_pair_edges(plan, geometry, vertices, mixed)]
    component = components_without(
        geometry, np.concatenate([cell_a, cut[:, 0]]), np.concatenate([cell_b, cut[:, 1]])
    )
    by_group = _single_label(component[cell[known]], label[known], int(component.max()) + 1)
    zones = by_group[component].astype(np.int32)
    by_cell = _single_label(cell[known], label[known], geometry.n_cells)
    labelled = np.zeros(geometry.n_cells, dtype=bool)
    labelled[cell[known]] = True
    zones[labelled] = by_cell[labelled]
    zones[mixed] = -1
    return zones


def _single_label(owner: np.ndarray, label: np.ndarray, size: int) -> np.ndarray:
    """The label of each owner when all its labels agree, ``-1`` otherwise or without one."""
    low = np.full(size, np.iinfo(np.int64).max, dtype=np.int64)
    high = np.full(size, -1, dtype=np.int64)
    np.minimum.at(low, owner, label)
    np.maximum.at(high, owner, label)
    return np.where((high >= 0) & (low == high), high, -1)


def _first_per_edge(rows: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """The first of *rows* on each edge, in row order."""
    _, first = np.unique(edges[rows], return_index=True)
    return rows[np.sort(first)]


def _shared_rows(
    faces: FaceLineState,
    family: int,
    segments: np.ndarray,
    edges: np.ndarray,
    own: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Rows of the faces *family* shares with an earlier family, and whether to flip them.

    A row is flipped where the line of *family* runs against the segment. Each
    face is listed once, and never when the family already holds it.
    """
    picked = faces.shared_family == family
    row_of = {int(segment): k for k, segment in enumerate(segments.tolist())}
    found = [
        (row_of[segment], reverse)
        for segment, reverse in zip(
            faces.shared_segment[picked].tolist(),
            faces.shared_reversed[picked].tolist(),
            strict=True,
        )
        if segment in row_of
    ]
    if not found:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=bool)
    rows = np.asarray([row for row, _ in found], dtype=np.int64)
    flip = np.asarray([reverse for _, reverse in found], dtype=bool)
    _, first = np.unique(edges[rows], return_index=True)
    first = np.sort(first)
    keep = first[~np.isin(edges[rows[first]], edges[own])]
    return rows[keep], flip[keep]


def _mirror_faces(
    plan: ConstraintPlan, geometry: DerivedGeometry, vertices: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Segment, cells ``(plus, minus)``, oriented nodes and edge row of each pair face found.

    Segments that share one pair share one face, so an edge row may repeat.
    """
    faces = plan.faces
    segments = np.flatnonzero(faces.segment_conformal & (faces.segment_seeds >= 0).all(axis=1))
    cells = faces.segment_seeds[segments]
    edge = geometry.edge_between(cells[:, 0], cells[:, 1])
    found = edge >= 0
    segments, cells, edge = segments[found], cells[found], edge[found]
    nodes = geometry.edge_nodes[edge]
    start = faces.vertices[faces.segment_nodes[segments, 0]]
    forward = np.hypot(*(vertices[nodes[:, 0]] - start).T) <= np.hypot(
        *(vertices[nodes[:, 1]] - start).T
    )
    return segments, cells, np.where(forward[:, None], nodes, nodes[:, ::-1]), edge


def _side_faces(
    geometry: DerivedGeometry, vertices: np.ndarray
) -> list[tuple[str, dict[str, np.ndarray]]]:
    """The families ``boundary:<side>`` of the boundary edges on each side of the vertex box.

    The side of an edge is the one :func:`box_side_of_edges` gives it. Its nodes
    run with its cell on their left; ``cell_b`` is ``-1``.
    """
    outer = np.flatnonzero(geometry.edge_cells[:, 1] < 0)
    pairs = geometry.edge_nodes[outer]
    side = box_side_of_edges(vertices, pairs[:, 0], pairs[:, 1])
    sides = []
    for index, name in enumerate(BOX_SIDES):
        on_side = side == index
        if not on_side.any():
            continue
        cell = geometry.edge_cells[outer[on_side], 0]
        nodes = pairs[on_side]
        tangent = vertices[nodes[:, 1]] - vertices[nodes[:, 0]]
        reach = geometry.area_centroids[cell] - vertices[nodes[:, 0]]
        left = tangent[:, 0] * reach[:, 1] - tangent[:, 1] * reach[:, 0] > 0.0
        nodes = np.where(left[:, None], nodes, nodes[:, ::-1])
        sides.append(
            (
                f"boundary:{name}",
                {
                    "cell_a": cell,
                    "cell_b": np.full(cell.size, -1),
                    "node_a": nodes[:, 0],
                    "node_b": nodes[:, 1],
                },
            )
        )
    return sides


def _loose_segments(plan: ConstraintPlan) -> np.ndarray:
    """The geology segments without their pair, as shapely lines in the local frame."""
    faces = plan.faces
    if GEOLOGY_FAMILY not in plan.family_names:
        return np.empty(0, dtype=object)
    loose = np.flatnonzero(
        ~faces.segment_conformal & (faces.segment_family == plan.family_names.index(GEOLOGY_FAMILY))
    )
    return shapely.linestrings(faces.vertices[faces.segment_nodes[loose]]).reshape(-1)


def _lost_pair_edges(
    plan: ConstraintPlan, geometry: DerivedGeometry, vertices: np.ndarray, mixed: np.ndarray
) -> np.ndarray:
    """Interior edges of a mixed cell or touched by a geology segment without its pair."""
    inner = geometry.edge_cells[:, 1] >= 0
    hit = inner & np.isin(geometry.edge_cells, mixed).any(axis=1)
    segments = _loose_segments(plan)
    if segments.size:
        edges = shapely.linestrings(vertices[geometry.edge_nodes])
        touched = STRtree(edges).query(segments, predicate="intersects")[1]
        hit[touched] = True
    return np.flatnonzero(hit & inner)


def _mixed_cells(
    plan: ConstraintPlan, geometry: DerivedGeometry, vertices: np.ndarray
) -> np.ndarray:
    """Cells whose interior a geology segment without its pair crosses.

    Each cell is shrunk by the face tolerance of the QA first, so a segment
    running on a cell edge does not count.
    """
    segments = _loose_segments(plan)
    if not segments.size:
        return np.empty(0, dtype=np.int64)
    tolerance = RELATIVE_FACE_TOLERANCE * float(np.median(geometry.edge_length))
    return mixed_cells(shapely.multilinestrings(segments), geometry, vertices, tolerance)

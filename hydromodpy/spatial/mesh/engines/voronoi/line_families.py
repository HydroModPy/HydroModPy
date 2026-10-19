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

from hydromodpy.spatial.mesh.engines.triangle.families import components_without
from hydromodpy.spatial.mesh.engines.voronoi.constraints import ConstraintPlan
from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry
from hydromodpy.spatial.mesh.model.mesh_qa import RELATIVE_FACE_TOLERANCE
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, FaceFamilyTable

__all__ = ["GEOLOGY_FAMILY", "cell_chains", "cell_zones", "face_family_table"]

GEOLOGY_FAMILY = "geology"
"""The face family whose two sides carry the zones of the cells."""

MIXED_TRAVERSAL = 1.0e-6
"""A line crosses a cell when its length inside exceeds this share of the cell side."""

_SIDES = ("west", "east", "south", "north")


def cell_chains(plan: ConstraintPlan) -> tuple[CellChain, ...]:
    """One chain per cell family line, the cells of its seeds, with their lateral offsets."""
    return tuple(
        CellChain(family=chain.family, chain_id=k, cell_ids=chain.seed_ids, offset_m=chain.offset_m)
        for k, chain in enumerate(plan.chains)
    )


def face_family_table(
    plan: ConstraintPlan, geometry: DerivedGeometry, vertices: np.ndarray
) -> FaceFamilyTable | None:
    """The faces of the mirror pairs and of the box sides, one row per mesh edge.

    A row of a face family is the edge between the cells of the pair of a
    conformal segment, ``cell_a`` (the ``plus`` seed) on the left of the line,
    its nodes in the order of the line. A conformal segment next to a yielded
    vertex whose pair shares no edge has no row; the QA coverage shows it.
    """
    names: list[str] = []
    columns: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    segments, cells, nodes = _mirror_faces(plan, geometry, vertices)
    faces = plan.faces
    for index, name in enumerate(plan.family_names):
        rows = faces.segment_family[segments] == index
        if not rows.any():
            continue
        names.append(name)
        zones = np.column_stack([faces.zone_left[segments[rows]], faces.zone_right[segments[rows]]])
        columns.append((cells[rows], nodes[rows], zones))
    for side, side_cells, side_nodes in _side_faces(geometry, vertices):
        names.append(f"boundary:{side}")
        columns.append((side_cells, side_nodes, np.full((len(side_cells), 2), -1)))
    if not names:
        return None
    count = [len(part[0]) for part in columns]
    cells = np.vstack([part[0] for part in columns])
    nodes = np.vstack([part[1] for part in columns])
    zones = np.vstack([part[2] for part in columns])
    return FaceFamilyTable(
        names=tuple(names),
        family=np.repeat(np.arange(len(names)), count),
        cell_a=cells[:, 0],
        cell_b=cells[:, 1],
        node_a=nodes[:, 0],
        node_b=nodes[:, 1],
        zone_left=zones[:, 0],
        zone_right=zones[:, 1],
    )


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
    cut = geometry.edge_cells[_yielded_edges(plan, geometry, vertices, mixed)]
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


def _mirror_faces(
    plan: ConstraintPlan, geometry: DerivedGeometry, vertices: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Segment, cells ``(plus, minus)`` and oriented nodes of each pair face found.

    Segments that share one pair share one face: it is listed once, under the
    first of them.
    """
    faces = plan.faces
    segments = np.flatnonzero(faces.segment_conformal & (faces.segment_seeds >= 0).all(axis=1))
    cells = faces.segment_seeds[segments]
    edge = _edge_of_cells(geometry, cells[:, 0], cells[:, 1])
    found = edge >= 0
    segments, cells, edge = segments[found], cells[found], edge[found]
    _, first = np.unique(edge, return_index=True)
    first.sort()
    segments, cells, edge = segments[first], cells[first], edge[first]
    nodes = geometry.edge_nodes[edge]
    start = faces.vertices[faces.segment_nodes[segments, 0]]
    forward = np.hypot(*(vertices[nodes[:, 0]] - start).T) <= np.hypot(
        *(vertices[nodes[:, 1]] - start).T
    )
    return segments, cells, np.where(forward[:, None], nodes, nodes[:, ::-1])


def _edge_of_cells(geometry: DerivedGeometry, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Edge row between cells ``a[i]`` and ``b[i]``, ``-1`` when they share no edge."""
    n = np.int64(geometry.n_cells)
    interior = np.flatnonzero(geometry.edge_cells[:, 1] >= 0)
    if not interior.size:
        return np.full(len(a), -1, dtype=np.int64)
    key = geometry.edge_cells[interior, 0] * n + geometry.edge_cells[interior, 1]
    order = np.argsort(key, kind="stable")
    sorted_key = key[order]
    probe = np.minimum(a, b) * n + np.maximum(a, b)
    position = np.minimum(np.searchsorted(sorted_key, probe), key.size - 1)
    found = (sorted_key[position] == probe) & (a != b)
    return np.where(found, interior[order][position], -1)


def _side_faces(
    geometry: DerivedGeometry, vertices: np.ndarray
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """Boundary edges on each side of the vertex box: ``(side, cells, nodes)``.

    A boundary edge belongs to the first side whose box line its midpoint lies
    on, within ``1e-8`` of the larger span (``1e-9`` m at least). Its nodes run
    with its cell on their left; ``cell_b`` is ``-1``.
    """
    outer = np.flatnonzero(geometry.edge_cells[:, 1] < 0)
    pairs = geometry.edge_nodes[outer]
    xmin, ymin = vertices.min(axis=0)
    xmax, ymax = vertices.max(axis=0)
    tolerance = max(1.0e-9, 1.0e-8 * max(xmax - xmin, ymax - ymin, 1.0))
    middle = 0.5 * (vertices[pairs[:, 0]] + vertices[pairs[:, 1]])
    lines = (middle[:, 0], middle[:, 0], middle[:, 1], middle[:, 1])
    free = np.ones(outer.size, dtype=bool)
    sides = []
    for side, coordinate, value in zip(_SIDES, lines, (xmin, xmax, ymin, ymax), strict=True):
        on_side = free & (np.abs(coordinate - value) <= tolerance)
        free &= ~on_side
        if not on_side.any():
            continue
        cell = geometry.edge_cells[outer[on_side], 0]
        nodes = pairs[on_side]
        tangent = vertices[nodes[:, 1]] - vertices[nodes[:, 0]]
        reach = geometry.area_centroids[cell] - vertices[nodes[:, 0]]
        left = tangent[:, 0] * reach[:, 1] - tangent[:, 1] * reach[:, 0] > 0.0
        nodes = np.where(left[:, None], nodes, nodes[:, ::-1])
        sides.append((side, np.column_stack([cell, np.full(cell.size, -1)]), nodes))
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


def _yielded_edges(
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
    padded = geometry.padded_connectivity.astype(np.int64)
    valid = padded >= 0
    corner = np.where(valid, padded, 0)
    x, y = vertices[corner, 0], vertices[corner, 1]
    boxes = shapely.box(
        np.where(valid, x, np.inf).min(axis=1),
        np.where(valid, y, np.inf).min(axis=1),
        np.where(valid, x, -np.inf).max(axis=1),
        np.where(valid, y, -np.inf).max(axis=1),
    )
    near = np.unique(STRtree(boxes).query(segments, predicate="intersects")[1])
    if not near.size:
        return near
    count = valid[near].sum(axis=1)
    pick = np.minimum(np.arange(padded.shape[1])[None, :], (count - 1)[:, None])
    rings = vertices[np.take_along_axis(padded[near], pick, axis=1)]
    tolerance = RELATIVE_FACE_TOLERANCE * float(np.median(geometry.edge_length))
    polygons = shapely.buffer(shapely.polygons(shapely.linearrings(rings)), -tolerance)
    inside = shapely.length(shapely.intersection(polygons, shapely.multilinestrings(segments)))
    return near[inside > MIXED_TRAVERSAL * np.sqrt(geometry.areas[near])]

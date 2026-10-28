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
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.strtree import STRtree

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.model.derived_geometry import (
    BOX_SIDES,
    DerivedGeometry,
    box_side_of_edges,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, FaceFamilyTable
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest

__all__ = [
    "EdgeLookup",
    "FamilyEdges",
    "TriangleFamilies",
    "box_side_edges",
    "cell_zones",
    "chains_of",
    "components_without",
    "edge_lookup",
    "face_table",
    "families_from_labels",
    "families_from_line_edges",
    "families_from_matching",
    "matching_tolerance",
    "request_zone_names",
]

_RIVER_LABEL = "river::"
_INTERFACE_LABEL = "interface::"
_WATERSHED_LABEL = "watershed::"
_BOUNDARY_LABEL = "boundary::"


@dataclass(frozen=True, eq=False)
class FamilyEdges:
    """The oriented mesh edges of one family, in line order.

    ``line`` is the source line of each row; ``forward`` is false where the row
    was flipped against its line to keep a cell on its left.
    """

    name: str
    node_a: np.ndarray
    node_b: np.ndarray
    cell_a: np.ndarray
    cell_b: np.ndarray
    zone_left: np.ndarray
    zone_right: np.ndarray
    line: np.ndarray
    forward: np.ndarray

    def line_vertices(self, line: int) -> np.ndarray:
        """The vertex ids along one source line, in the line direction."""
        rows = np.flatnonzero(self.line == line)
        start = np.where(self.forward[rows], self.node_a[rows], self.node_b[rows])
        stop = np.where(self.forward[rows], self.node_b[rows], self.node_a[rows])
        sequence = np.concatenate([start[:1], stop]) if rows.size else np.empty(0, np.int64)
        return _without_repeats(sequence)


@dataclass(frozen=True, eq=False)
class TriangleFamilies:
    """Every family of one triangulation and the zone names its rows index."""

    families: tuple[FamilyEdges, ...]
    zone_names: tuple[str, ...]
    cell_families: tuple[str, ...]

    def get(self, name: str) -> FamilyEdges | None:
        """The family named *name*, or ``None``."""
        return next((family for family in self.families if family.name == name), None)


@dataclass(frozen=True, eq=False)
class EdgeLookup:
    """Directed edges of counter-clockwise triangles, keyed ``a * n_nodes + b``.

    The edge table of ``DerivedGeometry`` is undirected, so it cannot say which
    triangle lies on the left of ``a -> b``; this one can.
    """

    n_nodes: int
    keys: np.ndarray
    cells: np.ndarray
    ccw: np.ndarray

    def cell_left_of(self, node_a: np.ndarray, node_b: np.ndarray) -> np.ndarray:
        """The triangle on the left of each directed edge ``a -> b``, ``-1`` if none."""
        wanted = np.asarray(node_a, np.int64) * self.n_nodes + np.asarray(node_b, np.int64)
        position = np.minimum(np.searchsorted(self.keys, wanted), self.keys.size - 1)
        return np.where(self.keys[position] == wanted, self.cells[position], -1)

    def fan(self, start: int, pivot: int, stop: int) -> list[int]:
        """Triangles met turning clockwise around ``pivot``, from ``start`` on.

        ``start`` is the triangle left of an edge that ends at ``pivot``. The
        list holds the triangles after ``start`` up to the one left of
        ``pivot -> stop``; it is empty when the fan reaches the boundary first.
        """
        cells: list[int] = []
        current = start
        for _ in range(self.keys.size):
            corners = self.ccw[current].tolist()
            following = corners[(corners.index(pivot) + 1) % 3]
            if following == stop:
                return cells
            current = int(self.cell_left_of(np.array([following]), np.array([pivot]))[0])
            if current < 0:
                return []
            cells.append(current)
        return []


def edge_lookup(vertices: np.ndarray, triangles: np.ndarray) -> EdgeLookup:
    """Index the directed edges of the triangles taken counter-clockwise."""
    corners = vertices[triangles]
    cross = (corners[:, 1, 0] - corners[:, 0, 0]) * (corners[:, 2, 1] - corners[:, 0, 1]) - (
        corners[:, 1, 1] - corners[:, 0, 1]
    ) * (corners[:, 2, 0] - corners[:, 0, 0])
    ccw = np.where((cross < 0.0)[:, None], triangles[:, [0, 2, 1]], triangles)
    source = ccw.ravel()
    target = ccw[:, [1, 2, 0]].ravel()
    n_nodes = len(vertices)
    keys = source.astype(np.int64) * n_nodes + target
    order = np.argsort(keys, kind="stable")
    cells = np.repeat(np.arange(len(triangles), dtype=np.int64), 3)
    return EdgeLookup(n_nodes=n_nodes, keys=keys[order], cells=cells[order], ccw=ccw)


def _without_repeats(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.int64)
    if values.size == 0:
        return values
    return values[np.concatenate([[True], values[1:] != values[:-1]])]


def _oriented_rows(
    name: str,
    lookup: EdgeLookup,
    edges: np.ndarray,
    line: np.ndarray,
    zone_left: np.ndarray,
    zone_right: np.ndarray,
) -> FamilyEdges:
    """Rows of oriented edges, flipped where only the right side is a cell."""
    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    left = lookup.cell_left_of(edges[:, 0], edges[:, 1])
    right = lookup.cell_left_of(edges[:, 1], edges[:, 0])
    missing = (left < 0) & (right < 0)
    if np.any(missing):
        a, b = edges[np.flatnonzero(missing)[0]]
        raise MeshGenerationError(f"family {name!r}: edge ({a}, {b}) is not a triangle edge")
    forward = left >= 0
    return FamilyEdges(
        name=name,
        node_a=np.where(forward, edges[:, 0], edges[:, 1]),
        node_b=np.where(forward, edges[:, 1], edges[:, 0]),
        cell_a=np.where(forward, left, right),
        cell_b=np.where(forward, right, -1),
        zone_left=np.where(forward, zone_left, zone_right).astype(np.int32),
        zone_right=np.where(forward, zone_right, zone_left).astype(np.int32),
        line=np.asarray(line, dtype=np.int64),
        forward=forward,
    )


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


def request_zone_names(request: MeshRequest) -> tuple[str, ...]:
    """Sorted zone names of every family of the request."""
    names = {zone for family in request.lines for zone in (*family.zone_left, *family.zone_right)}
    return tuple(sorted(names))


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
            _oriented_rows(
                family.name, lookup, np.concatenate(edges), line, left[line], right[line]
            )
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
    return _oriented_rows(family.name, lookup, pairs[order], line, left[line], right[line])


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


def _walks(edges: np.ndarray) -> list[np.ndarray]:
    """Split undirected edges into polylines through the vertices of degree two.

    Each polyline is an ``(k, 2)`` array of oriented vertex pairs, in order.
    """
    if edges.size == 0:
        return []
    incident: dict[int, list[int]] = {}
    for index, (a, b) in enumerate(edges.tolist()):
        incident.setdefault(a, []).append(index)
        incident.setdefault(b, []).append(index)
    used = np.zeros(len(edges), dtype=bool)
    ends = sorted(node for node, items in incident.items() if len(items) != 2)
    starts = ends + sorted(incident)
    walks: list[np.ndarray] = []
    for start in starts:
        for first in incident[start]:
            if used[first]:
                continue
            node, edge, walk = start, first, []
            while not used[edge]:
                used[edge] = True
                a, b = edges[edge]
                nxt = b if a == node else a
                walk.append((node, nxt))
                node = nxt
                if len(incident[node]) != 2:
                    break
                edge = next(item for item in incident[node] if item != edge)
            walks.append(np.asarray(walk, dtype=np.int64))
    return walks


def _label_family(label: str) -> str:
    if label.startswith(_RIVER_LABEL):
        return "rivers"
    if label.startswith(_INTERFACE_LABEL):
        return "geology"
    if label.startswith(_WATERSHED_LABEL):
        return "watershed_boundary"
    return f"boundary:{label.removeprefix(_BOUNDARY_LABEL)}"


def families_from_labels(
    edge_labels: Mapping[str, np.ndarray], lookup: EdgeLookup, geometry: DerivedGeometry
) -> tuple[tuple[FamilyEdges, ...], tuple[str, ...], tuple[str, ...]]:
    """Families of a read triangulation from its physical line groups.

    ``river::*`` gives ``rivers`` (a cell family, one line per walk through
    degree-two vertices), ``interface::<a>::<b>`` gives ``geology`` with zones
    ``a`` and ``b`` set on the side each one fills, ``watershed::*`` gives
    ``watershed_boundary`` and any other group ``boundary:<name>`` (its
    boundary edges only). Returns the families, the zone names and the notes.
    """
    grouped: dict[str, list[tuple[str, np.ndarray]]] = {}
    for label, edges in edge_labels.items():
        if len(edges):
            grouped.setdefault(_label_family(label), []).append((label, np.asarray(edges)))
    zone_names = tuple(
        sorted(
            {
                zone
                for label in edge_labels
                if label.startswith(_INTERFACE_LABEL)
                for zone in label.removeprefix(_INTERFACE_LABEL).split("::")
            }
        )
    )
    notes: list[str] = []
    families: list[FamilyEdges] = []
    for name in sorted(grouped):
        parts = grouped[name]
        if name == "geology":
            families.append(_labelled_geology(parts, lookup, geometry, zone_names))
            continue
        walks = _walks(np.concatenate([edges for _, edges in parts]))
        edges = np.concatenate(walks)
        line = np.repeat(np.arange(len(walks)), [len(walk) for walk in walks])
        unknown = np.full(len(edges), -1, dtype=np.int32)
        rows = _oriented_rows(name, lookup, edges, line, unknown, unknown)
        if name.startswith("boundary:"):
            outer = rows.cell_b < 0
            if not np.all(outer):
                notes.append(
                    f"{int((~outer).sum())} interior edges of the .msh group of {name} are not "
                    "a boundary face and are left out"
                )
            rows = _subset(rows, outer)
        families.append(rows)
    return tuple(families), zone_names, tuple(notes)


def _subset(rows: FamilyEdges, keep: np.ndarray) -> FamilyEdges:
    return FamilyEdges(
        name=rows.name,
        **{
            column: getattr(rows, column)[keep]
            for column in (
                "node_a",
                "node_b",
                "cell_a",
                "cell_b",
                "zone_left",
                "zone_right",
                "line",
                "forward",
            )
        },
    )


def components_without(
    geometry: DerivedGeometry, cut_a: np.ndarray, cut_b: np.ndarray
) -> np.ndarray:
    """Connected components of the cells once the faces ``cut_a | cut_b`` are cut."""
    n_cells = geometry.n_cells
    inner = geometry.edge_cells[geometry.edge_cells[:, 1] >= 0]
    inner_keys = inner[:, 0] * n_cells + inner[:, 1]
    inside = cut_b >= 0
    cut_keys = np.minimum(cut_a, cut_b)[inside] * n_cells + np.maximum(cut_a, cut_b)[inside]
    kept = inner[~np.isin(inner_keys, cut_keys)]
    graph = coo_matrix((np.ones(len(kept)), (kept[:, 0], kept[:, 1])), shape=(n_cells, n_cells))
    return connected_components(graph, directed=False)[1]


def _labelled_geology(
    parts: list[tuple[str, np.ndarray]],
    lookup: EdgeLookup,
    geometry: DerivedGeometry,
    zone_names: tuple[str, ...],
) -> FamilyEdges:
    """Geology rows of ``interface::a::b`` groups, each zone set on the side it fills.

    A group name does not say which zone lies left of its edges. The component
    of cells between interfaces whose pairs share one zone takes it, and the
    zone propagates across each interface to the other side.
    """
    index = {name: position for position, name in enumerate(zone_names)}
    pairs = [
        tuple(index[zone] for zone in label.removeprefix(_INTERFACE_LABEL).split("::"))
        for label, _ in parts
    ]
    edges = np.concatenate([edges for _, edges in parts])
    group = np.repeat(np.arange(len(parts)), [len(edges) for _, edges in parts])
    unknown = np.full(len(edges), -1, dtype=np.int32)
    rows = _oriented_rows("geology", lookup, edges, group, unknown, unknown)
    component = components_without(geometry, rows.cell_a, rows.cell_b)
    side_a = component[rows.cell_a]
    side_b = np.where(rows.cell_b >= 0, component[np.maximum(rows.cell_b, 0)], -1)

    candidates: dict[int, set[int]] = {}
    for row in range(len(edges)):
        pair = set(pairs[group[row]])
        for comp in (int(side_a[row]), int(side_b[row])):
            if comp >= 0:
                candidates[comp] = candidates.get(comp, pair) & pair
    zone_of = {comp: next(iter(zones)) for comp, zones in candidates.items() if len(zones) == 1}
    changed = True
    while changed:
        changed = False
        for row in range(len(edges)):
            a, b = int(side_a[row]), int(side_b[row])
            pair = pairs[group[row]]
            if b < 0 or len(pair) != 2:
                continue
            for known, other in ((a, b), (b, a)):
                if known in zone_of and other not in zone_of and zone_of[known] in pair:
                    zone_of[other] = pair[1] if zone_of[known] == pair[0] else pair[0]
                    changed = True
    zone_left = np.asarray([zone_of.get(c, -1) for c in side_a.tolist()], dtype=np.int32)
    zone_right = np.asarray(
        [zone_of.get(c, -1) if c >= 0 else -1 for c in side_b.tolist()], dtype=np.int32
    )
    return FamilyEdges(
        name=rows.name,
        node_a=rows.node_a,
        node_b=rows.node_b,
        cell_a=rows.cell_a,
        cell_b=rows.cell_b,
        zone_left=zone_left,
        zone_right=zone_right,
        line=rows.line,
        forward=rows.forward,
    )


def box_side_edges(
    vertices: np.ndarray, geometry: DerivedGeometry, lookup: EdgeLookup
) -> tuple[FamilyEdges, ...]:
    """Families ``boundary:<side>`` of the boundary edges on each side of the vertex box.

    The side of an edge is the one :func:`box_side_of_edges` gives it.
    """
    outer = np.flatnonzero(geometry.edge_cells[:, 1] < 0)
    pairs = geometry.edge_nodes[outer]
    side = box_side_of_edges(vertices, pairs[:, 0], pairs[:, 1])
    families = []
    for index, name in enumerate(BOX_SIDES):
        on_side = side == index
        if not np.any(on_side):
            continue
        unknown = np.full(int(on_side.sum()), -1, dtype=np.int32)
        families.append(
            _oriented_rows(
                f"boundary:{name}",
                lookup,
                pairs[on_side],
                np.full(unknown.size, -1),
                unknown,
                unknown,
            )
        )
    return tuple(families)


def face_table(families: tuple[FamilyEdges, ...]) -> FaceFamilyTable | None:
    """The face family table of every family with at least one row."""
    present = [family for family in families if family.cell_a.size]
    if not present:
        return None
    return FaceFamilyTable.stack(
        [
            (
                family.name,
                {
                    "cell_a": family.cell_a,
                    "cell_b": family.cell_b,
                    "node_a": family.node_a,
                    "node_b": family.node_b,
                    "zone_left": family.zone_left,
                    "zone_right": family.zone_right,
                },
            )
            for family in present
        ]
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
            CellChain(family=family.name, chain_id=len(chains), cell_ids=_without_repeats(cells))
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

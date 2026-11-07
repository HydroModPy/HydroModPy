"""Line families of a read triangulation, from the physical line groups of its ``.msh``.

A group ``river::<name>`` gives a river, ``interface::<a>::<b>`` a geology
contact between zones ``a`` and ``b``, ``watershed::<name>`` the catchment
outline, and any other group a side of the domain boundary.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.mesh.cells.regions import components_without
from hydromodpy.mesh.engines.face_families import EdgeLookup, FamilyEdges, oriented_rows
from hydromodpy.mesh.planar.geometry import DerivedGeometry

__all__ = ["families_from_labels"]

_RIVER_LABEL = "river::"

_INTERFACE_LABEL = "interface::"

_WATERSHED_LABEL = "watershed::"

_BOUNDARY_LABEL = "boundary::"


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
        rows = oriented_rows(name, lookup, edges, line, unknown, unknown)
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
    rows = oriented_rows("geology", lookup, edges, group, unknown, unknown)
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

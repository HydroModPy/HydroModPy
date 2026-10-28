"""Resample the family lines at the local cell size, before any engine.

The fixed nodes are the line ends, the confluences, the crossings between
any two lines, the contacts with the domain boundary and the corners of a
barrier line, so a barrier keeps its exact course. Between two fixed
nodes a line is cut into ``n`` segments of equal ``integral ds / h``: each
segment is about one local cell long, and none is shorter than 0.8 local
cell, except a whole edge between two fixed nodes that is shorter than that.
Such an edge is kept whole and counted.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.ops import substring
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.model.derived_geometry import polygon_rings
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, LineFamilySpec, SizeField

__all__ = [
    "KINK_MIN_SHARE",
    "KINK_TURN_RAD",
    "MIN_SEGMENT_SHARE",
    "ResampledFamilies",
    "kink_pieces",
    "node_tolerance",
    "positions_at_local_size",
    "resample_families",
]

MIN_SEGMENT_SHARE = 0.8
"""Shortest segment, as a share of the local cell size, between two fixed nodes."""

_RING_SEGMENTS = 3
"""Fewest segments of a closed line with no other fixed node."""

_NODE_TOL_REL = 1.0e-9
"""Distance under which a fixed node lies on a line, as a share of the domain extent."""

_SAMPLES_PER_CELL = 4
"""Samples of ``h`` per smallest cell size along a line."""

KINK_TURN_RAD = math.radians(20.0)
"""A vertex of a barrier line turning more than this angle is a fixed node, unless
one of its two segments is shorter than :data:`KINK_MIN_SHARE` of the finest size
of the field: no cell resolves such a corner, and keeping it only folds the line
within a cell."""

KINK_MIN_SHARE = 0.5
"""Shortest segment beside a kept corner, as a share of the finest size. A line
already resampled has segments of 0.8 cell at least, so it keeps its corners."""


@dataclass(frozen=True)
class ResampledFamilies:
    """The resampled families, and how many fixed edges stayed shorter than 0.8 cell."""

    families: tuple[LineFamilySpec, ...]
    short_fixed_edges: int


def resample_families(
    families: Sequence[LineFamilySpec],
    *,
    domain: Polygon,
    size_field: SizeField,
    fixed_points: np.ndarray | None = None,
) -> ResampledFamilies:
    """Resample every line of *families* on *size_field*; names, zones and orientation kept.

    *fixed_points* ``(k, 2)`` are fixed nodes besides those of the noded lines:
    a line that passes on one keeps it as a vertex.
    """
    lines = [line for family in families for line in family.lines]
    if not lines:
        return ResampledFamilies(families=tuple(families), short_fixed_edges=0)
    tol = node_tolerance(domain)
    extra = (
        [np.asarray(fixed_points, dtype=float).reshape(-1, 2)] if fixed_points is not None else []
    )
    shortest = KINK_MIN_SHARE * float(size_field.values.min())
    extra += [
        _kinks(line, shortest)
        for family in families
        if family.name == BARRIER_FAMILY
        for line in family.lines
    ]
    nodes = np.unique(np.vstack([_fixed_nodes(lines, domain), *extra]), axis=0)
    tree = STRtree(shapely.points(nodes))
    cover = domain.buffer(tol)
    shapely.prepare(cover)
    step = float(size_field.values.min()) / _SAMPLES_PER_CELL
    size_at = size_field.sample
    short = 0
    resampled: list[LineFamilySpec] = []
    for family in families:
        new_lines = []
        for line in family.lines:
            new_line, line_short = _resample_line(line, nodes, tree, tol, step, size_at, cover)
            new_lines.append(new_line)
            short += line_short
        resampled.append(replace(family, lines=tuple(new_lines)))
    return ResampledFamilies(families=tuple(resampled), short_fixed_edges=short)


def node_tolerance(domain: Polygon) -> float:
    """Distance [m] under which a fixed node lies on a line: 1e-9 of the domain extent."""
    minx, miny, maxx, maxy = domain.bounds
    return max(_NODE_TOL_REL * max(maxx - minx, maxy - miny), 1.0e-9)


def _fixed_nodes(lines: list[LineString], domain: Polygon) -> np.ndarray:
    """Coordinates ``(k, 2)`` of the ends of the noded union of the lines and the boundary."""
    rings = polygon_rings(domain)
    noded = shapely.get_parts(shapely.node(shapely.multilinestrings([*lines, *rings])))
    ends = np.concatenate(
        [
            shapely.get_coordinates(shapely.get_point(noded, 0)),
            shapely.get_coordinates(shapely.get_point(noded, -1)),
        ]
    )
    return np.unique(ends, axis=0)


def kink_pieces(line: LineString) -> list[LineString]:
    """*line* cut at the vertices where it turns by more than :data:`KINK_TURN_RAD`."""
    coords = shapely.get_coordinates(line)
    cuts = [0, *(_kink_indices(coords) + 1).tolist(), len(coords) - 1]
    return [LineString(coords[a : b + 1]) for a, b in zip(cuts[:-1], cuts[1:], strict=True)]


def _kinks(line: LineString, shortest: float) -> np.ndarray:
    """The inner vertices ``(k, 2)`` where *line* turns by more than :data:`KINK_TURN_RAD`.

    A vertex is kept only when its two segments are at least *shortest* [m] long.
    """
    coords = shapely.get_coordinates(line)
    kinks = _kink_indices(coords)
    length = np.hypot(*np.diff(coords, axis=0).T)
    kept = (length[kinks] >= shortest) & (length[kinks + 1] >= shortest)
    return coords[1:-1][kinks[kept]]


def _kink_indices(coords: np.ndarray) -> np.ndarray:
    """Indices into ``coords[1:-1]`` of the inner vertices that turn by more than the kink angle."""
    if len(coords) < 3:
        return np.empty(0, dtype=np.int64)
    step = np.diff(coords, axis=0)
    heading = np.arctan2(step[:, 1], step[:, 0])
    turn = np.abs(np.mod(np.diff(heading) + np.pi, 2.0 * np.pi) - np.pi)
    return np.flatnonzero(turn > KINK_TURN_RAD)


def _resample_line(
    line: LineString,
    nodes: np.ndarray,
    tree: STRtree,
    tol: float,
    step: float,
    size_at: Callable[[np.ndarray], np.ndarray],
    cover: Polygon,
) -> tuple[LineString, int]:
    """One line cut at its fixed nodes, each piece resampled; returns the short piece count."""
    stops = _stops(line, nodes, tree, tol)
    ring = line.is_closed and len(stops) == 2
    distances: list[float] = [stops[0][0]]
    coords: list[np.ndarray] = [stops[0][1]]
    short = 0
    for (start, _), (end, end_xy) in zip(stops[:-1], stops[1:], strict=True):
        inner, positions, piece_short = positions_at_local_size(
            substring(line, start, end), step, size_at, ring=ring
        )
        distances.extend(start + positions)
        coords.extend(inner)
        distances.append(end)
        coords.append(end_xy)
        short += piece_short
    xy = _keep_inside(line, np.asarray(distances), np.vstack(coords), cover, tol)
    return LineString(xy), short


def _keep_inside(
    line: LineString, distances: np.ndarray, xy: np.ndarray, cover: Polygon, tol: float
) -> np.ndarray:
    """Add original vertices to every chord of the new line that leaves *cover*."""
    original = shapely.get_coordinates(line)
    along = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(original, axis=0).T))))
    while True:
        chords = shapely.linestrings(np.stack([xy[:-1], xy[1:]], axis=1))
        outside = np.flatnonzero(~shapely.covers(cover, chords))
        picks: list[tuple[int, int]] = []
        for index in outside:
            low = np.searchsorted(along, distances[index] + tol, side="left")
            high = np.searchsorted(along, distances[index + 1] - tol, side="right")
            if high <= low:
                continue
            offsets = shapely.distance(chords[index], shapely.points(original[low:high]))
            picks.append((index + 1, low + int(np.argmax(offsets))))
        if not picks:
            return xy
        at = [position for position, _ in picks]
        vertex = [vertex for _, vertex in picks]
        distances = np.insert(distances, at, along[vertex])
        xy = np.insert(xy, at, original[vertex], axis=0)


def _stops(
    line: LineString, nodes: np.ndarray, tree: STRtree, tol: float
) -> list[tuple[float, np.ndarray]]:
    """Fixed nodes on *line* as ``(distance along, xy)``, both ends included, in line order.

    Stops closer than *tol* merge; a merged stop takes the coordinates of a
    fixed node when it holds one, so the lines that meet there share them.
    """
    length = line.length
    first = np.asarray(line.coords[0], dtype=float)
    last = np.asarray(line.coords[-1], dtype=float)
    if length <= tol:
        return [(0.0, first), (length, last)]
    entries = [(0.0, first, False), (length, last, False)]
    for index in tree.query(line, predicate="dwithin", distance=tol):
        xy = nodes[index]
        entries.append((float(line.project(shapely.Point(xy))), xy, True))
    entries.sort(key=lambda entry: entry[0])
    clusters: list[list[tuple[float, np.ndarray, bool]]] = []
    for entry in entries:
        if clusters and entry[0] - clusters[-1][-1][0] <= tol:
            clusters[-1].append(entry)
        else:
            clusters.append([entry])
    stops = []
    for cluster in clusters:
        distance = cluster[0][0]
        if distance <= tol:
            distance = 0.0
        elif cluster[-1][0] >= length - tol:
            distance = length
        xy = next((entry[1] for entry in cluster if entry[2]), cluster[0][1])
        stops.append((distance, xy))
    if line.is_closed:
        stops[-1] = (length, stops[0][1])
    return stops


def positions_at_local_size(
    piece: LineString,
    step: float,
    size_at: Callable[[np.ndarray], np.ndarray],
    *,
    ring: bool,
) -> tuple[list[np.ndarray], np.ndarray, int]:
    """New vertices strictly inside *piece*, their distances along it, and the short flag.

    ``size_at`` maps coordinates ``(k, 2)`` to the local cell size [m], in the
    frame of *piece*. ``step`` [m] is the spacing of the samples of ``1 / h``. The
    piece is cut into ``n`` segments of equal ``integral ds / h``. The flag is 1
    when the segments of the piece stay under 0.8 cell.
    """
    length = piece.length
    count = max(2, math.ceil(length / step) + 1)
    along = np.linspace(0.0, length, count)
    xy = shapely.get_coordinates(shapely.line_interpolate_point(piece, along))
    inverse = 1.0 / size_at(xy)
    cumulative = np.concatenate(
        ([0.0], np.cumsum(0.5 * (inverse[1:] + inverse[:-1]) * np.diff(along)))
    )
    total = float(cumulative[-1])
    segments = max(1, round(total))
    if segments > 1 and total / segments < MIN_SEGMENT_SHARE:
        segments -= 1
    if ring:
        segments = max(segments, _RING_SEGMENTS)
    short = int(total / segments < MIN_SEGMENT_SHARE)
    if segments == 1:
        return [], np.empty(0), short
    targets = total * np.arange(1, segments) / segments
    positions = np.interp(targets, cumulative, along)
    points = shapely.get_coordinates(shapely.line_interpolate_point(piece, positions))
    return list(points), positions, short

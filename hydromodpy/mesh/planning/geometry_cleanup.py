"""Clean the geometry of the project inputs before the planner sizes it.

Small defects of vector data reach the engine otherwise: two vertices a few
centimeters apart, a river that stops one meter short of the boundary, a
contact that runs along another one before it ends, a hole of one square
meter in a lake. Each one seeds cells a few meters apart, which the engine
either over-refines or refuses.

The planner first drops the holes smaller than one local cell squared
(:func:`drop_small_holes`). Then :func:`clean_lines` works on the lines the
mesh follows and on the domain, at a tolerance of a share of the DEM pixel.
It leaves alone what touches exactly and what lies farther than the
tolerance, so a clean input passes unchanged. Each change is counted by
kind, and the counts become notes of the request.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.mesh_config import MeshFamiliesConfig
from hydromodpy.mesh.planar.geometry import polygon_rings
from hydromodpy.mesh.planning.inputs import PlanningInputs
from hydromodpy.mesh.resample import node_tolerance

__all__ = [
    "CLEANUP_PIXEL_SHARE",
    "STUB_TOLERANCES",
    "GeometryCleanup",
    "OutlineSmoothing",
    "clean_lines",
    "drop_small_holes",
]

_logger = get_logger(__name__)

CLEANUP_PIXEL_SHARE = 0.1
"""Cleanup tolerance as a share of the DEM pixel: 1 m on a 10 m DEM."""

STUB_TOLERANCES = 2.0
"""Length, in tolerances, past which a line end inside the band of another line is cut.

A line that arrives across another one spends one tolerance in its band; one
that runs along it spends more, and that stretch is a sliver no cell resolves.
"""


@dataclass(frozen=True)
class OutlineSmoothing:
    """What the smoothing of one outline changed (``catchment_outline.py``).

    ``area_shift`` is the share of the area that moved and ``shift_m`` the
    largest distance [m] between a vertex of one outline and the other.
    ``cut_m`` and ``simplify_m`` are the corner cut and the simplification
    tolerance [m].
    """

    name: str
    vertices_before: int
    vertices_after: int
    area_shift: float
    shift_m: float
    cut_m: float
    simplify_m: float


@dataclass
class GeometryCleanup:
    """What the cleanup changed, counted by kind.

    ``smoothed`` holds the outlines whose staircase was smoothed and
    ``unsmoothed`` the names of those that stayed as they were because the
    smoothed polygon was not valid.
    """

    tolerance: float
    merged_vertices: int = 0
    cut_ends: int = 0
    snapped_ends: int = 0
    dropped_holes: int = 0
    smoothed: list[OutlineSmoothing] = field(default_factory=list)
    unsmoothed: list[str] = field(default_factory=list)

    def notes(self) -> tuple[str, ...]:
        """One note per kind of change made, for the QA of the mesh."""
        tol = f"{self.tolerance:g} m"
        notes = []
        for outline in self.smoothed:
            notes.append(
                f"geometry cleanup: the {outline.name} outline was smoothed, each corner of "
                f"its pixel steps cut at {outline.cut_m:g} m and the line simplified at "
                f"{outline.simplify_m:g} m: {outline.vertices_before} vertices became "
                f"{outline.vertices_after}, its area moved by {100.0 * outline.area_shift:.2f} % "
                f"and no point of it by more than {outline.shift_m:.1f} m"
            )
        for name in self.unsmoothed:
            notes.append(
                f"geometry cleanup: the {name} outline stayed a staircase, since its "
                "smoothed polygon was not valid"
            )
        if self.merged_vertices:
            notes.append(
                f"geometry cleanup: {self.merged_vertices} line vertices closer than {tol} "
                "to the previous one were merged"
            )
        if self.cut_ends:
            notes.append(
                f"geometry cleanup: {self.cut_ends} line ends that ran within {tol} "
                "along another line were cut back"
            )
        if self.snapped_ends:
            notes.append(
                f"geometry cleanup: {self.snapped_ends} line ends within {tol} "
                "of another line were snapped onto it"
            )
        if self.dropped_holes:
            notes.append(
                f"{self.dropped_holes} holes of the domain, the lakes and the catchment were "
                "smaller than one local cell squared and were dropped"
            )
        return tuple(notes)

    def log(self) -> None:
        """Write each count in the journal."""
        for outline in self.smoothed:
            _logger.info(
                "Smoothed the %s outline: %d vertices became %d, area moved by %.2f %%.",
                outline.name,
                outline.vertices_before,
                outline.vertices_after,
                100.0 * outline.area_shift,
            )
        for name in self.unsmoothed:
            _logger.warning(
                "The %s outline stayed a staircase: smoothing it left it invalid.", name
            )
        for count, message in (
            (self.merged_vertices, "Merged %d line vertices closer than %g m."),
            (self.cut_ends, "Cut back %d line ends that ran within %g m along another line."),
            (self.snapped_ends, "Snapped %d line ends within %g m of another line."),
        ):
            if count:
                _logger.info(message, count, self.tolerance)
        if self.dropped_holes:
            _logger.info(
                "Dropped %d holes smaller than one local cell squared.", self.dropped_holes
            )


def clean_lines(
    inputs: PlanningInputs,
    families: MeshFamiliesConfig,
    cleanup: GeometryCleanup,
) -> PlanningInputs:
    """The inputs with close vertices merged and loose line ends cut back and snapped.

    Only the domain and the families *families* asks for are cleaned. The
    vertices of every line and ring closer than the tolerance to the previous
    one are merged; the ends of open lines stay, and so does a vertex that
    another line or ring also has, so a wall laid on a shore stays on it.
    Then each end of an open line (river, barrier, contact) within the
    tolerance of another line or ring, without touching it, is snapped onto
    it. A river or contact end is first cut back when it ran along that other
    line; a barrier keeps its length, which its flow barrier carries.
    *cleanup* receives the counts.
    """
    tol = cleanup.tolerance
    lakes_on = families.lakes == "face"
    watershed_on = families.watershed_boundary == "face" and inputs.watershed is not None
    river_lines = (
        tuple(inputs.river_trace.lines)
        if families.rivers == "cell" and inputs.river_trace is not None
        else ()
    )
    barrier_lines = inputs.barriers if families.barriers == "face" else ()
    contact_lines = (
        inputs.geology.lines if families.geology == "face" and inputs.geology is not None else ()
    )
    polygons = [inputs.domain, *(inputs.lakes if lakes_on else ())]
    if watershed_on:
        polygons.append(inputs.watershed)
    pinned = _shared_vertices([*polygons, *river_lines, *barrier_lines, *contact_lines])

    domain = _merged_polygon(inputs.domain, tol, pinned, cleanup)
    lakes = inputs.lakes
    if lakes_on:
        lakes = tuple(_merged_polygon(lake, tol, pinned, cleanup) for lake in lakes)
    watershed = inputs.watershed
    if watershed_on:
        watershed = _merged_polygon(watershed, tol, pinned, cleanup)
    rivers = [_merged_line(line, tol, pinned, cleanup) for line in river_lines]
    barriers = [_merged_line(line, tol, pinned, cleanup) for line in barrier_lines]
    contacts = [_merged_line(line, tol, pinned, cleanup) for line in contact_lines]

    rings = polygon_rings(
        domain, *(lakes if lakes_on else ()), *([watershed] if watershed_on else [])
    )
    open_lines = _ends_cleaned(
        [*rivers, *barriers, *contacts],
        [True] * len(rivers) + [False] * len(barriers) + [True] * len(contacts),
        rings,
        tol,
        node_tolerance(domain),
        cleanup,
    )
    rivers = open_lines[: len(rivers)]
    barriers = open_lines[len(rivers) : len(rivers) + len(barriers)]
    contacts = open_lines[len(rivers) + len(barriers) :]

    changes: dict[str, object] = {}
    if domain is not inputs.domain:
        changes["domain"] = domain
    if _changed(lakes, inputs.lakes):
        changes["lakes"] = lakes
    if watershed is not inputs.watershed:
        changes["watershed"] = watershed
    if rivers and inputs.river_trace is not None and _changed(rivers, inputs.river_trace.lines):
        changes["river_trace"] = replace(inputs.river_trace, lines=tuple(rivers))
    if barriers and _changed(barriers, inputs.barriers):
        changes["barriers"] = tuple(barriers)
    if contacts and inputs.geology is not None and _changed(contacts, inputs.geology.lines):
        changes["geology"] = replace(inputs.geology, lines=tuple(contacts))
    return replace(inputs, **changes) if changes else inputs


def drop_small_holes(
    inputs: PlanningInputs,
    size_at: Callable[[np.ndarray], np.ndarray],
    cleanup: GeometryCleanup,
) -> PlanningInputs:
    """The inputs without the holes whose area is under the squared local size.

    The local size is read at the representative point of the hole. The domain,
    the lakes and the catchment are cleaned; the lake keeps its polygon in the
    flow model, only the ring that the mesh would follow goes. *cleanup*
    receives the count.
    """
    dropped = 0

    def cleaned(polygon: Polygon | None) -> Polygon | None:
        nonlocal dropped
        if polygon is None or polygon.geom_type != "Polygon" or not polygon.interiors:
            return polygon
        kept = []
        for ring in polygon.interiors:
            hole = Polygon(ring)
            size = float(size_at(np.asarray(hole.representative_point().coords))[0])
            if hole.area < size * size:
                dropped += 1
            else:
                kept.append(ring)
        return polygon if len(kept) == len(polygon.interiors) else Polygon(polygon.exterior, kept)

    domain = cleaned(inputs.domain)
    lakes = tuple(cleaned(lake) for lake in inputs.lakes)
    watershed = cleaned(inputs.watershed)
    if not dropped:
        return inputs
    cleanup.dropped_holes += dropped
    return replace(inputs, domain=domain, lakes=lakes, watershed=watershed)


def _changed(new: Iterable[BaseGeometry], old: Iterable[BaseGeometry]) -> bool:
    """Whether any geometry of *new* is another object than its source."""
    return any(a is not b for a, b in zip(new, old, strict=True))


def _shared_vertices(geometries: Iterable[BaseGeometry]) -> frozenset[tuple[float, float]]:
    """The vertices that two or more of *geometries* have, at the same coordinates."""
    seen: set[tuple[float, float]] = set()
    shared: set[tuple[float, float]] = set()
    for geometry in geometries:
        own = {(float(x), float(y)) for x, y in shapely.get_coordinates(geometry)}
        shared |= own & seen
        seen |= own
    return frozenset(shared)


def _merged_coords(
    coords: np.ndarray, tol: float, pinned: frozenset[tuple[float, float]]
) -> np.ndarray:
    """*coords* without the vertices closer than *tol* to the last one kept.

    Both ends and the *pinned* vertices stay; a free vertex kept just before
    one of them goes when it lies closer than *tol*.
    """
    last = len(coords) - 1
    fixed = [
        index in (0, last) or (float(x), float(y)) in pinned for index, (x, y) in enumerate(coords)
    ]
    keep = [0]
    for index in range(1, len(coords)):
        if fixed[index]:
            while (
                len(keep) > 1
                and not fixed[keep[-1]]
                and np.hypot(*(coords[index] - coords[keep[-1]])) < tol
            ):
                keep.pop()
            keep.append(index)
        elif np.hypot(*(coords[index] - coords[keep[-1]])) >= tol:
            keep.append(index)
    return coords[keep]


def _merged_line(
    line: LineString, tol: float, pinned: frozenset[tuple[float, float]], cleanup: GeometryCleanup
) -> LineString:
    """*line* with its close vertices merged, or *line* itself when none is."""
    coords = np.asarray(line.coords)[:, :2]
    merged = _merged_coords(coords, tol, pinned)
    if len(merged) == len(coords):
        return line
    cleanup.merged_vertices += len(coords) - len(merged)
    return LineString(merged)


def _merged_polygon(
    polygon: Polygon, tol: float, pinned: frozenset[tuple[float, float]], cleanup: GeometryCleanup
) -> Polygon:
    """*polygon* with the close vertices of its rings merged, or *polygon* when none is.

    A ring that would fall under three vertices keeps its own, and a polygon
    that would turn invalid keeps all of them. The planner drops the small
    holes first (:func:`drop_small_holes`), so few rings get there.
    """
    if polygon.geom_type != "Polygon":
        return polygon
    rings = [np.asarray(polygon.exterior.coords)[:, :2]]
    rings += [np.asarray(ring.coords)[:, :2] for ring in polygon.interiors]
    merged = [_merged_coords(ring, tol, pinned) for ring in rings]
    merged = [new if len(new) >= 4 else old for old, new in zip(rings, merged, strict=True)]
    removed = sum(len(old) - len(new) for old, new in zip(rings, merged, strict=True))
    if not removed:
        return polygon
    candidate = Polygon(merged[0], merged[1:])
    if not candidate.is_valid:
        return polygon
    cleanup.merged_vertices += removed
    return candidate


def _ends_cleaned(
    lines: list[LineString],
    cuttable: list[bool],
    rings: list[LineString],
    tol: float,
    touch: float,
    cleanup: GeometryCleanup,
) -> list[LineString]:
    """*lines* with each end near another line or ring snapped onto it.

    The end of a *cuttable* line is first cut back when it ran along that
    line or ring. The lines are visited in order, head then tail, and each change is seen by
    the ends visited after it: two ends that miss each other meet once.
    """
    current = [*lines, *rings]
    if not lines:
        return lines
    tree = shapely.STRtree(current)
    for index in range(len(lines)):
        for head in (True, False):
            line = current[index]
            end = Point(line.coords[0] if head else line.coords[-1])
            near = [
                int(other)
                for other in tree.query(end, predicate="dwithin", distance=2.0 * tol)
                if other != index
            ]
            if not near:
                continue
            distances = shapely.distance(end, [current[other] for other in near])
            closest = int(np.argmin(distances))
            if distances[closest] <= touch or distances[closest] > tol:
                continue
            target = current[near[closest]]
            if cuttable[index]:
                line = _cut_stub(line, target, tol, touch, head=head, cleanup=cleanup)
            current[index] = _snapped(line, target, tol, head=head, cleanup=cleanup)
    return current[: len(lines)]


def _cut_stub(
    line: LineString,
    target: LineString,
    tol: float,
    touch: float,
    *,
    head: bool,
    cleanup: GeometryCleanup,
) -> LineString:
    """*line* without its end stretch in the *tol* band of *target*, when that runs along it.

    The stretch is cut when it is longer than ``STUB_TOLERANCES * tol`` and
    shorter than the line: a line wholly in the band keeps its length.
    """
    end = Point(line.coords[0] if head else line.coords[-1])
    stretch = 0.0
    for part in shapely.get_parts(line.intersection(target.buffer(tol))):
        if isinstance(part, LineString) and part.distance(end) <= touch:
            stretch = part.length
    if stretch <= STUB_TOLERANCES * tol or stretch >= line.length - touch:
        return line
    cleanup.cut_ends += 1
    if head:
        return substring(line, stretch, line.length)
    return substring(line, 0.0, line.length - stretch)


def _snapped(
    line: LineString, target: LineString, tol: float, *, head: bool, cleanup: GeometryCleanup
) -> LineString:
    """*line* with one end moved onto *target*: on its nearest vertex within *tol*, else its nearest point."""
    coords = np.asarray(line.coords)[:, :2].copy()
    end = coords[0] if head else coords[-1]
    vertices = np.asarray(target.coords)[:, :2]
    gaps = np.hypot(*(vertices - end).T)
    if gaps.min() <= tol:
        new_end = vertices[int(np.argmin(gaps))]
    else:
        new_end = np.asarray(target.interpolate(target.project(Point(end))).coords)[0, :2]
    coords[0 if head else -1] = new_end
    neighbour = coords[1] if head else coords[-2]
    if len(coords) == 2 and np.array_equal(neighbour, new_end):
        return line
    if np.array_equal(neighbour, new_end):
        coords = coords[1:] if head else coords[:-1]
    cleanup.snapped_ends += 1
    return LineString(coords)

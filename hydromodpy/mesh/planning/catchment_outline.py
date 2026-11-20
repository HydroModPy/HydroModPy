"""Smooth the staircase of the catchment outline before the planner reads it.

The catchment polygon comes from a raster delineation, so its outline is a
staircase of DEM pixels. A graded engine that follows it, as the face family
``watershed_boundary`` or as the domain outline, would have to follow every
step: its cells narrow to a pixel along the outline and leave thin ones
between the steps and the cells beside them.

The planner smooths the outline once, before the size field and the families
read it. Each corner of a step is cut at half a pixel, then the line is
simplified at half a pixel (Douglas-Peucker). A step of one pixel on a
diagonal falls on its middle line, so the area barely moves, and no point of
the new outline lies farther than a pixel from the staircase.

A corner between two edges longer than two pixels belongs to the shape, not to
a staircase, and stays: a rectangle is left as it is. So does every vertex
that another line touches, a river end, a barrier end or a lake shore, and the
outlet of the catchment when it lies on the outline: the outline keeps touching
them. The polygons of the flow model are not changed, only the outline the mesh
follows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.mesh.mesh_config import MeshFamiliesConfig
from hydromodpy.mesh.planar.geometry import polygon_rings
from hydromodpy.mesh.planning.geometry_cleanup import (
    CLEANUP_PIXEL_SHARE,
    GeometryCleanup,
    OutlineSmoothing,
)
from hydromodpy.mesh.planning.inputs import PlanningInputs

__all__ = [
    "OUTLINE_CUT_SHARE",
    "OUTLINE_SIMPLIFY_SHARE",
    "STAIR_EDGE_SHARE",
    "smooth_catchment",
    "smooth_polygon",
]

OUTLINE_CUT_SHARE = 0.5
"""Distance at which a corner of a step is cut, as a share of the DEM pixel.

Half a pixel is the middle of a one-pixel step: the cut corners of a diagonal
staircase then meet on its middle line, and a convex corner loses what the
concave one beside it gains.
"""

OUTLINE_SIMPLIFY_SHARE = 0.5
"""Douglas-Peucker tolerance after the cut, as a share of the DEM pixel.

With the cut it keeps every point of the new outline within 0.85 pixel of the
staircase.
"""

STAIR_EDGE_SHARE = 2.0
"""Longest edge of a step, in pixels.

A corner is smoothed when one of its two edges is this short or shorter. A
corner between two longer edges is a corner of the shape.
"""

_SAME_OUTLINE_TOL = 1.0e-6
"""Distance [m] under which two polygons are the same outline."""


def smooth_catchment(
    inputs: PlanningInputs,
    families: MeshFamiliesConfig,
    cleanup: GeometryCleanup,
    pixel: float,
) -> PlanningInputs:
    """The inputs with the outline of the catchment smoothed where the mesh follows it.

    The mesh follows the catchment when ``families.watershed_boundary`` is
    ``face`` or when the domain is the catchment; a domain that is a buffer
    of it is smoothed on its own, a rectangle is left alone. The domain keeps
    the very outline of the catchment when it is the catchment. A river end,
    a barrier end, a lake shore or the outlet that touches the outline still
    touches it. *cleanup* receives what changed.
    """
    watershed = inputs.watershed
    if watershed is None:
        return inputs
    domain = inputs.domain
    lines = _followed_geometries(inputs, families)
    changes: dict[str, object] = {}
    if _same_outline(domain, watershed):
        smooth = _smoothed(watershed, pixel, lines, "catchment and domain", cleanup)
        if smooth is not watershed:
            changes = {"watershed": smooth, "domain": smooth}
    else:
        outlines = [("domain", "domain", domain, watershed)]
        if families.watershed_boundary == "face":
            outlines.insert(0, ("watershed", "catchment", watershed, domain))
        for key, name, polygon, other in outlines:
            smooth = _smoothed(polygon, pixel, [*lines, *_lines_of(other.boundary)], name, cleanup)
            if smooth is not polygon:
                changes[key] = smooth
    return replace(inputs, **changes) if changes else inputs


def smooth_polygon(
    polygon: Polygon, pixel: float, touching: Sequence[BaseGeometry] = ()
) -> Polygon | None:
    """*polygon* with the staircase of its rings smoothed, or None when that leaves it invalid.

    *polygon* itself comes back when no corner of a step is left to smooth.
    The vertices of *touching* within ``CLEANUP_PIXEL_SHARE * pixel`` of an
    outline are kept on it, and so is every outline vertex that close to them.
    """
    if polygon.geom_type != "Polygon" or polygon.is_empty:
        return polygon
    others = shapely.GeometryCollection(list(touching)) if touching else None
    if others is not None:
        shapely.prepare(others)
    rings = []
    changed = False
    for ring in polygon_rings(polygon):
        coords = np.asarray(ring.coords)[:, :2]
        smooth = _smoothed_ring(coords, pixel, others)
        changed = changed or smooth is not None
        rings.append(coords if smooth is None else smooth)
    if not changed:
        return polygon
    candidate = Polygon(rings[0], rings[1:])
    if candidate.is_empty or not candidate.is_valid:
        return None
    return candidate


def _smoothed(
    polygon: Polygon,
    pixel: float,
    touching: Sequence[BaseGeometry],
    name: str,
    cleanup: GeometryCleanup,
) -> Polygon:
    """The smoothed *polygon*, counted in *cleanup*; *polygon* itself when nothing changes."""
    smooth = smooth_polygon(polygon, pixel, touching)
    if smooth is None:
        cleanup.unsmoothed.append(name)
        return polygon
    if smooth is polygon:
        return polygon
    cleanup.smoothed.append(
        OutlineSmoothing(
            name=name,
            vertices_before=len(shapely.get_coordinates(polygon)),
            vertices_after=len(shapely.get_coordinates(smooth)),
            area_shift=abs(smooth.area - polygon.area) / polygon.area,
            shift_m=_largest_shift(polygon, smooth),
            cut_m=OUTLINE_CUT_SHARE * pixel,
            simplify_m=OUTLINE_SIMPLIFY_SHARE * pixel,
        )
    )
    return smooth


def _same_outline(domain: Polygon, watershed: Polygon) -> bool:
    """Whether the domain is the catchment: same rings, up to float noise."""
    return bool(shapely.equals_exact(domain, watershed, tolerance=_SAME_OUTLINE_TOL))


def _followed_geometries(
    inputs: PlanningInputs, families: MeshFamiliesConfig
) -> list[BaseGeometry]:
    """What may touch the catchment outline: the lines the mesh follows and the outlet.

    The outlet is kept whatever the families are, so a catchment without river
    family keeps it on the outline as well.
    """
    geometries: list[BaseGeometry] = []
    if families.rivers == "cell" and inputs.river_trace is not None:
        geometries.extend(inputs.river_trace.lines)
    if families.barriers == "face":
        geometries.extend(inputs.barriers)
    if families.geology == "face" and inputs.geology is not None:
        geometries.extend(inputs.geology.lines)
    if families.lakes == "face":
        geometries.extend(lake.boundary for lake in inputs.lakes)
    touching: list[BaseGeometry] = [line for geometry in geometries for line in _lines_of(geometry)]
    if inputs.outlet is not None:
        touching.append(inputs.outlet)
    return touching


def _lines_of(geometry: BaseGeometry) -> list[LineString]:
    """The line parts of *geometry*; the rings of a polygon, not its area."""
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        geometry = geometry.boundary
    return [
        part
        for part in shapely.get_parts(geometry)
        if isinstance(part, LineString) and not part.is_empty
    ]


def _smoothed_ring(
    coords: np.ndarray, pixel: float, touching: BaseGeometry | None
) -> np.ndarray | None:
    """The closed ring *coords* smoothed, or None when it has no corner of a step."""
    points = coords[:-1]
    points = points[np.hypot(*(points - np.roll(points, 1, axis=0)).T) > 0.0]
    if len(points) < 4:
        return None
    tol = CLEANUP_PIXEL_SHARE * pixel
    points, pinned = _with_contacts(points, touching, tol)
    free = _step_corners(points, pixel) & ~pinned
    if not free.any():
        return None
    cut, anchors = _cut_corners(points, free, OUTLINE_CUT_SHARE * pixel)
    ring = _simplified(cut, anchors, OUTLINE_SIMPLIFY_SHARE * pixel)
    return ring if len(ring) >= 4 else None


def _with_contacts(
    points: np.ndarray, touching: BaseGeometry | None, tol: float
) -> tuple[np.ndarray, np.ndarray]:
    """The ring *points* with a vertex where *touching* meets it, and the vertices to keep.

    A vertex of *touching* within *tol* of the ring and farther than *tol* from
    every ring vertex adds its projection on the ring as a vertex. Every
    vertex within *tol* of *touching* is kept as it is.
    """
    if touching is None:
        return points, np.zeros(len(points), dtype=bool)
    ring = LineString(np.vstack([points, points[:1]]))
    shapely.prepare(ring)
    vertices = np.unique(shapely.get_coordinates(touching), axis=0)
    near = vertices[shapely.dwithin(ring, shapely.points(vertices), tol)]
    if len(near):
        points = _with_projections(points, ring, near, tol)
    pinned = shapely.dwithin(touching, shapely.points(points), tol)
    return points, np.asarray(pinned, dtype=bool)


def _with_projections(
    points: np.ndarray, ring: LineString, near: np.ndarray, tol: float
) -> np.ndarray:
    """*points* with the projection of each point of *near* that no vertex lies within *tol* of."""
    tree = shapely.STRtree(shapely.points(points))
    served = set(tree.query(shapely.points(near), predicate="dwithin", distance=tol)[0].tolist())
    kept: list[np.ndarray] = []
    for index in sorted(set(range(len(near))) - served):
        if not any(np.hypot(*(near[index] - other)) <= tol for other in kept):
            kept.append(near[index])
    if not kept:
        return points
    along = np.array([ring.project(shapely.Point(xy)) for xy in kept])
    along.sort()
    edge_ends = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(ring.coords, axis=0).T))))
    positions = np.searchsorted(edge_ends, along, side="right")
    new = shapely.get_coordinates(shapely.line_interpolate_point(ring, along))
    return np.insert(points, positions, new, axis=0)


def _step_corners(points: np.ndarray, pixel: float) -> np.ndarray:
    """Vertices of the ring with an edge no longer than ``STAIR_EDGE_SHARE`` pixels."""
    before = np.hypot(*(points - np.roll(points, 1, axis=0)).T)
    after = np.hypot(*(np.roll(points, -1, axis=0) - points).T)
    return np.minimum(before, after) <= STAIR_EDGE_SHARE * pixel * (1.0 + 1.0e-9)


def _cut_corners(
    points: np.ndarray, free: np.ndarray, distance: float
) -> tuple[np.ndarray, np.ndarray]:
    """The ring with each *free* vertex cut into two, and the positions of the vertices not cut.

    A corner is cut at *distance* along each of its edges, or at the middle of
    an edge shorter than twice that.
    """
    back = np.roll(points, 1, axis=0) - points
    ahead = np.roll(points, -1, axis=0) - points
    back_len = np.hypot(*back.T)
    ahead_len = np.hypot(*ahead.T)
    first = points + back * (np.minimum(distance, 0.5 * back_len) / back_len)[:, None]
    second = points + ahead * (np.minimum(distance, 0.5 * ahead_len) / ahead_len)[:, None]
    both = np.empty((2 * len(points), 2))
    both[0::2] = np.where(free[:, None], first, points)
    both[1::2] = np.where(free[:, None], second, points)
    keep = np.ones(2 * len(points), dtype=bool)
    keep[1::2] = free
    sizes = 1 + free.astype(int)
    starts = np.cumsum(sizes) - sizes
    return both[keep], starts[~free]


def _simplified(cut: np.ndarray, anchors: np.ndarray, tolerance: float) -> np.ndarray:
    """The closed ring of *cut* simplified between its *anchors*, which stay.

    Each stretch from one anchor to the next is simplified on its own, so an
    anchor is a vertex of the result. A ring without anchor keeps its first
    vertex.
    """
    if len(anchors) == 0:
        return _simplified_line(np.vstack([cut, cut[:1]]), tolerance)
    rolled = np.vstack([np.roll(cut, -int(anchors[0]), axis=0), cut[int(anchors[0])][None]])
    stops = np.append(anchors - anchors[0], len(cut))
    stretches = [
        _simplified_line(rolled[start : stop + 1], tolerance)
        for start, stop in zip(stops[:-1], stops[1:], strict=True)
    ]
    return np.vstack([stretches[0], *(stretch[1:] for stretch in stretches[1:])])


def _simplified_line(line: np.ndarray, tolerance: float) -> np.ndarray:
    """*line* simplified at *tolerance* with its ends kept and no repeated vertex."""
    if len(line) > 2:
        line = shapely.get_coordinates(
            shapely.simplify(shapely.linestrings(line), tolerance, preserve_topology=True)
        )
    apart = np.hypot(*np.diff(line, axis=0).T) > 1.0e-9 * max(tolerance, 1.0)
    keep = np.concatenate(([True], apart))
    if not keep[-1] and len(line) > 2:
        keep[-2:] = (False, True)
    return line[keep]


def _largest_shift(old: Polygon, new: Polygon) -> float:
    """The largest distance [m] from a vertex of one outline to the other."""
    worst = 0.0
    for source, target in ((old, new), (new, old)):
        tree = shapely.STRtree(_segments(target))
        points = shapely.points(shapely.get_coordinates(source))
        _, distances = tree.query_nearest(points, return_distance=True, all_matches=False)
        worst = max(worst, float(np.max(distances)))
    return worst


def _segments(polygon: Polygon) -> np.ndarray:
    """The segments of every ring of *polygon*, as line strings."""
    segments: list[np.ndarray] = []
    for ring in polygon_rings(polygon):
        coords = np.asarray(ring.coords)[:, :2]
        segments.append(shapely.linestrings(np.stack([coords[:-1], coords[1:]], axis=1)))
    return np.concatenate(segments)

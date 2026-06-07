"""River linework helpers used by the catchment mesh bundle export.

These helpers turn a ``river_trace`` payload into a shapely linework or a
fast matcher, then expose a per-segment river test consumed when building
the exported edge table.
"""

from __future__ import annotations

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from hydromodpy.spatial.mesh.gmsh_grid._river_linework_matching import (
    RiverLineworkMatcher,
)


def _iter_line_geometries(lines_attr: object | None) -> list[object]:
    """Flatten a `river_trace.lines`-like payload into individual line geometries."""
    if lines_attr is None:
        return []
    out: list[object] = []
    for geometry in tuple(lines_attr):
        if geometry is None or bool(getattr(geometry, "is_empty", True)):
            continue
        geom_type = str(getattr(geometry, "geom_type", ""))
        if geom_type == "LineString":
            out.append(geometry)
            continue
        if geom_type == "MultiLineString":
            out.extend(
                line
                for line in getattr(geometry, "geoms", ())
                if not bool(getattr(line, "is_empty", True))
            )
    return out


def _build_river_linework(river_trace: object | None):
    """Collapse a river-trace payload to one shapely linework object."""
    lines_attr = getattr(river_trace, "lines", None)
    river_lines = _iter_line_geometries(lines_attr)
    if not river_lines:
        return None
    return unary_union(river_lines)


def _build_river_matcher(
    *,
    river_trace: object | None,
    tolerance: float,
) -> RiverLineworkMatcher | None:
    """Build one reusable matcher for exported river edges."""
    lines_attr = getattr(river_trace, "lines", None)
    river_lines = _iter_line_geometries(lines_attr)
    if not river_lines:
        return None
    matcher = RiverLineworkMatcher(
        line_geometries=tuple(river_lines),
        tolerance=tolerance,
    )
    return matcher if matcher.available else None


def _segment_matches_river(
    segment: LineString,
    river_linework,
    *,
    tolerance: float,
) -> bool:
    """Return whether one exported edge segment belongs to the river trace."""
    if isinstance(river_linework, RiverLineworkMatcher):
        return river_linework.matches_segment(segment)
    if river_linework is None or bool(getattr(river_linework, "is_empty", True)):
        return False
    if float(river_linework.distance(segment)) > float(tolerance):
        return False
    checkpoints = (
        Point(segment.coords[0]),
        segment.interpolate(0.5, normalized=True),
        Point(segment.coords[-1]),
    )
    return all(float(river_linework.distance(point)) <= float(tolerance) for point in checkpoints)

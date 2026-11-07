"""Contacts between the zones of a vector geology map, as oriented lines.

A contact is the boundary two zones of different keys share. Each contact is
oriented so that the zone whose key sorts first lies on its left, and the
contacts are sorted, so the lines do not depend on the order of the polygons
in the source file.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.protocols import get_geology_data_source

__all__ = ["GeologyLines", "contact_lines", "geology_lines", "support_contacts"]

_RASTER_SUFFIXES = frozenset({".tif", ".tiff"})
_SIDE_PROBE_REL = 1.0e-7
"""Offset of the side probe, as a share of the map extent."""
_RING_QUAD_SEGS = 64
"""Segments per quarter of a ring contact: 0.01 m from a circle of 140 m."""


@dataclass(frozen=True)
class GeologyLines:
    """The contacts of a geology map, each with the zone on its left and on its right.

    ``zone_left`` and ``zone_right`` name one zone per line, as
    :func:`contact_lines` and :func:`support_contacts` build them.
    """

    lines: tuple[LineString, ...]
    zone_left: tuple[str, ...]
    zone_right: tuple[str, ...]


def geology_lines(
    config: Mapping[str, object], *, config_path: str | Path | None, crs_wkt: str
) -> GeologyLines | None:
    """Read the contacts of the geology support *config*, or None for a raster source.

    The zones are reprojected to *crs_wkt*, the CRS of the project; a map with no CRS is refused.

    A raster map has no exact contact: the mesh then ignores the geology lines
    and the zones are sampled on the cells, as before.
    """
    source = config.get("source")
    if not isinstance(source, Mapping) or not source.get("path"):
        raise MeshRequestError("a geology support needs source.path")
    kind = str(source.get("kind", "auto")).strip().lower()
    if kind == "raster" or (
        kind == "auto" and Path(str(source["path"])).suffix.lower() in _RASTER_SUFFIXES
    ):
        return None
    payload = get_geology_data_source().load_vector_dataframe(config, config_path=config_path)
    frame = payload["gdf"]
    if frame.crs is None:
        raise MeshRequestError(f"the geology map {source['path']!r} declares no CRS")
    frame = frame.to_crs(crs_wkt)
    return contact_lines(zip(frame["zone_key"], frame.geometry, strict=True))


def contact_lines(zones: Iterable[tuple[str, BaseGeometry]]) -> GeologyLines:
    """Return the shared boundaries between polygons of different zone keys."""
    by_zone: dict[str, list[BaseGeometry]] = {}
    for key, geometry in zones:
        if geometry is None or geometry.is_empty:
            continue
        if geometry.geom_type not in ("Polygon", "MultiPolygon"):
            raise MeshRequestError(f"geology zone {key!r} holds a {geometry.geom_type}")
        by_zone.setdefault(str(key), []).append(geometry)
    keys = sorted(by_zone)
    merged = [shapely.union_all(by_zone[key]) for key in keys]
    if not merged:
        return GeologyLines(lines=(), zone_left=(), zone_right=())
    minx, miny, maxx, maxy = shapely.total_bounds(merged)
    probe = _SIDE_PROBE_REL * max(maxx - minx, maxy - miny)
    tree = STRtree(merged)
    rows: list[tuple[str, str, LineString]] = []
    for first, second in sorted(
        (int(a), int(b)) for a, b in tree.query(merged, predicate="intersects").T if a < b
    ):
        shared = merged[first].boundary.intersection(merged[second].boundary)
        for line in _merged_lines(shared):
            left, right = keys[first], keys[second]
            if not _left_is(merged[first], line, probe):
                line = LineString(line.coords[::-1])
            rows.append((left, right, _canonical_start(line)))
    rows.sort(key=lambda row: (row[0], row[1], row[2].coords[0], row[2].coords[-1]))
    return GeologyLines(
        lines=tuple(row[2] for row in rows),
        zone_left=tuple(row[0] for row in rows),
        zone_right=tuple(row[1] for row in rows),
    )


def support_contacts(
    support: object, bounds: tuple[float, float, float, float]
) -> GeologyLines | None:
    """The contacts of the zones of an analytical support, or None for any other support.

    A ``generated_bands`` support cuts *bounds* along an axis at its breaks, a
    ``generated_rings`` support cuts it into concentric zones around its center.
    Coordinates are read as the support providers read them: a relative break is
    a share of the extent along the axis, a relative radius a share of the
    largest circle around the center that stays inside *bounds*. The zone keys
    are the labels of the support, so a mesh that follows the contacts names the
    zones the flow parameters read.
    """
    kind = getattr(support, "kind", None)
    if kind == "generated_bands":
        return contact_lines(_band_zones(support, bounds))
    if kind == "generated_rings":
        return contact_lines(_ring_zones(support, bounds))
    return None


def _band_zones(
    support: object, bounds: tuple[float, float, float, float]
) -> list[tuple[str, BaseGeometry]]:
    """The bands of a ``generated_bands`` support, as slices of *bounds*."""
    xmin, ymin, xmax, ymax = bounds
    along_x = support.axis == "x"
    low, high = (xmin, xmax) if along_x else (ymin, ymax)
    if support.coordinate_mode == "relative":
        breaks = [low + float(value) * (high - low) for value in support.breaks]
    else:
        breaks = [float(value) for value in support.breaks]
    if any(value <= low or value >= high for value in breaks):
        raise MeshRequestError(
            f"the breaks of the generated_bands support lie outside ({low}, {high})"
        )
    edges = [low, *breaks, high]
    return [
        (
            label,
            box(first, ymin, second, ymax) if along_x else box(xmin, first, xmax, second),
        )
        for label, first, second in zip(support.labels, edges[:-1], edges[1:], strict=True)
    ]


def _ring_zones(
    support: object, bounds: tuple[float, float, float, float]
) -> list[tuple[str, BaseGeometry]]:
    """The concentric zones of a ``generated_rings`` support, as discs and annuli of *bounds*."""
    xmin, ymin, xmax, ymax = bounds
    x = 0.5 * (xmin + xmax) if support.center_x is None else float(support.center_x)
    y = 0.5 * (ymin + ymax) if support.center_y is None else float(support.center_y)
    inscribed = min(x - xmin, xmax - x, y - ymin, ymax - y)
    if inscribed <= 0.0:
        raise MeshRequestError("the centre of the generated_rings support lies outside its domain")
    if support.coordinate_mode == "relative":
        radii = [float(value) * inscribed for value in support.radii]
    else:
        radii = [float(value) for value in support.radii]
    if any(value >= inscribed for value in radii):
        raise MeshRequestError(
            "the radii of the generated_rings support must lie inside the largest circle "
            "around its centre"
        )
    centre = Point(x, y)
    discs = [centre.buffer(radius, quad_segs=_RING_QUAD_SEGS) for radius in radii]
    outside = box(xmin, ymin, xmax, ymax)
    inner = [Polygon(), *discs]
    outer = [*discs, outside]
    return [
        (label, outward.difference(inward))
        for label, inward, outward in zip(support.labels, inner, outer, strict=True)
    ]


def _merged_lines(shared: BaseGeometry) -> list[LineString]:
    """The line parts of a boundary intersection, merged node to node; points dropped."""
    if shared.is_empty:
        return []
    return [
        part
        for part in shapely.get_parts(shapely.line_merge(shared))
        if isinstance(part, LineString) and part.length > 0.0
    ]


def _left_is(zone: BaseGeometry, line: LineString, probe: float) -> bool:
    """Whether *zone* lies left of the first segment of *line*."""
    coords = np.asarray(line.coords, dtype=float)
    start, end = coords[0], coords[1]
    middle = 0.5 * (start + end)
    direction = end - start
    normal = np.array([-direction[1], direction[0]]) / np.hypot(*direction)
    return bool(zone.contains(Point(middle + probe * normal)))


def _canonical_start(line: LineString) -> LineString:
    """A closed contact starts at its smallest vertex; an open one is left as is."""
    if not line.is_closed:
        return line
    coords = [tuple(xy) for xy in line.coords[:-1]]
    start = coords.index(min(coords))
    ring = coords[start:] + coords[:start]
    return LineString([*ring, ring[0]])

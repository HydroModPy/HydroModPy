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
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.protocols import get_geology_data_source

__all__ = ["GeologyLines", "contact_lines", "geology_lines"]

_RASTER_SUFFIXES = frozenset({".tif", ".tiff"})
_SIDE_PROBE_REL = 1.0e-7
"""Offset of the side probe, as a share of the map extent."""


@dataclass(frozen=True)
class GeologyLines:
    """The contacts of a geology map, each with the zone on its left and on its right."""

    lines: tuple[LineString, ...]
    zone_left: tuple[str, ...]
    zone_right: tuple[str, ...]

    def __post_init__(self) -> None:
        """Refuse zone lists that do not name one zone per line."""
        if not (len(self.lines) == len(self.zone_left) == len(self.zone_right)):
            raise MeshRequestError("geology contacts need one left and one right zone per line")


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

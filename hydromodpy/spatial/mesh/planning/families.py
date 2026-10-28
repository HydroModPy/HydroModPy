"""The line families of a mesh request, as ``[mesh.families]`` asks for them.

Each family line is clipped to the domain and oriented as its source. A
generated Voronoi mesh also gets the lake shores it can follow at its cell size
(``lake_shores.py``), and its rivers stay off the lake outlines by a margin.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.mesh.model.derived_geometry import polygon_rings
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.lake_shores import followed_lake_shores
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, LineFamilySpec, SizeField

RIVER_STUB_SHARE = 0.25
"""Share of a river part between two lakes cut back at each end, when that is
less than the margin: the middle half keeps its river cells."""

RIVER_MARGIN_SHARE = 0.5
"""Distance between a lake outline and the rivers of a generated Voronoi mesh, in river cells.

On the Cheze reservoir the shores close from 0.5 river cell (40 m) on, and
not at 0 or 0.25: a river end on the ring cuts it, and its last seed takes the
shore pairs.
"""


def _followed_shores(
    families: tuple[LineFamilySpec, ...],
    inputs: PlanningInputs,
    domain: Polygon,
    size_field: SizeField,
    *,
    margin: float,
) -> tuple[tuple[LineFamilySpec, ...], tuple[str, ...]]:
    """The families with the lake rings a generated Voronoi mesh can follow, and the notes.

    The rivers also stay *margin* off the outlines the mesh follows: a river
    that crossed a ring would bend it at the crossing.
    """
    river_lines = inputs.river_trace.lines if inputs.river_trace is not None else ()
    shores = followed_lake_shores(
        inputs.lakes,
        size_field.sample,
        barriers=inputs.barriers,
        rivers=tuple(river_lines),
        finest=float(size_field.values.min()),
    )
    lines, _ = _clipped(_rings(shores.polygons), domain)
    if not lines:
        return families, ()
    rivers: tuple[LineString, ...] = ()
    if inputs.river_trace is not None:
        lakes = (*inputs.lakes, *shores.polygons)
        rivers = _rivers_off_lakes(inputs.river_trace.lines, lakes, domain, margin)
    out = []
    for family in families:
        if family.name == "lakes":
            out.append(replace(family, lines=lines))
        elif family.name == "rivers":
            if rivers:
                out.append(replace(family, lines=rivers))
        else:
            out.append(family)
    return tuple(out), shores.notes()


def _families(
    mesh_cfg: MeshConfig, inputs: PlanningInputs, domain: Polygon, *, pixel: float
) -> tuple[LineFamilySpec, ...]:
    """The line families ``[mesh.families]`` asks for, clipped to *domain*."""
    wanted = mesh_cfg.families
    families: list[LineFamilySpec] = []
    if wanted.rivers == "cell" and inputs.river_trace is not None:
        if _follows_shores_by_pairs(mesh_cfg, inputs):
            margin = _river_margin(mesh_cfg, pixel)
            lines = _rivers_off_lakes(inputs.river_trace.lines, inputs.lakes, domain, margin)
        else:
            lines, _ = _clipped(inputs.river_trace.lines, domain)
        if lines:
            families.append(LineFamilySpec("rivers", "cell", lines))
    if wanted.geology == "face" and inputs.geology is not None:
        lines, zones = _clipped(
            inputs.geology.lines,
            domain,
            zip(inputs.geology.zone_left, inputs.geology.zone_right, strict=True),
        )
        if lines:
            families.append(
                LineFamilySpec(
                    "geology",
                    "face",
                    lines,
                    zone_left=tuple(left for left, _ in zones),
                    zone_right=tuple(right for _, right in zones),
                )
            )
    if wanted.lakes == "face" and inputs.lakes:
        lines, _ = _clipped(_rings(inputs.lakes), domain)
        if lines:
            families.append(LineFamilySpec("lakes", "face", lines, closed=True))
    if wanted.barriers == "face" and inputs.barriers:
        lines, _ = _clipped(inputs.barriers, domain)
        if lines:
            families.append(LineFamilySpec(BARRIER_FAMILY, "face", lines))
    if wanted.watershed_boundary == "face" and inputs.watershed is not None:
        lines, _ = _clipped(_rings((inputs.watershed,)), domain)
        if lines:
            families.append(LineFamilySpec("watershed_boundary", "face", lines, closed=True))
    return tuple(families)


def _river_margin(mesh_cfg: MeshConfig, pixel: float) -> float:
    """How far [m] a river of a generated Voronoi mesh stays off the lake outlines.

    Half a river cell: a river that ends on a ring would cut it there into
    short segments, and its last seed would sit on the shore pairs.
    """
    return RIVER_MARGIN_SHARE * max(mesh_cfg.river_cell_size or pixel, pixel)


def _rivers_off_lakes(
    lines: Iterable[LineString], lakes: Iterable[BaseGeometry], domain: Polygon, margin: float
) -> tuple[LineString, ...]:
    """The parts of *lines* in *domain* off the *lakes*, each end on a lake cut back.

    A lake replaces the river in its footprint: the reaches stop at the shore
    and hand their flow to the lake, so a river chain there would only take the
    cells of the shore pairs. An end on a lake is cut back by *margin* [m], or
    by a quarter of the part when it is short: a link between two lakes keeps
    its river cells, which its reach needs.
    """
    union = shapely.union_all(list(lakes))
    parts, _ = _clipped(lines, domain.difference(union))
    touch = 1.0e-6 * max(margin, 1.0)
    kept = []
    for part in parts:
        length = part.length
        cut = min(margin, RIVER_STUB_SHARE * length)
        head = cut if union.distance(shapely.Point(part.coords[0])) <= touch else 0.0
        tail = cut if union.distance(shapely.Point(part.coords[-1])) <= touch else 0.0
        if length - head - tail > 0.0:
            kept.append(substring(part, head, length - tail))
    return tuple(kept)


def _follows_shores_by_pairs(mesh_cfg: MeshConfig, inputs: PlanningInputs) -> bool:
    """Whether the engine lays mirror pairs on lake shores: a generated Voronoi mesh with lakes."""
    return (
        mesh_cfg.engine == "voronoi"
        and mesh_cfg.families.lakes == "face"
        and inputs.input_triangulation is None
        and bool(inputs.lakes)
    )


def _rings(polygons: Iterable[BaseGeometry]) -> list[LineString]:
    """Every ring of *polygons* in normalized form, sorted, so their order never counts."""
    parts = shapely.get_parts(list(polygons))
    rings = polygon_rings(*(shapely.normalize(polygon) for polygon in parts))
    return sorted(rings, key=lambda ring: tuple(map(tuple, ring.coords)))


def _clipped(
    lines: Iterable[LineString],
    domain: Polygon,
    tags: Iterable[object] | None = None,
) -> tuple[tuple[LineString, ...], list[object]]:
    """The parts of *lines* inside *domain*, each oriented as its source, with its tag."""
    tag_list = list(tags) if tags is not None else None
    parts_out: list[LineString] = []
    tags_out: list[object] = []
    for index, line in enumerate(lines):
        pieces = []
        for part in shapely.get_parts(shapely.line_merge(line.intersection(domain))):
            if not isinstance(part, LineString) or part.length <= 0.0:
                continue
            if _runs_backwards(part, line):
                part = LineString(part.coords[::-1])
            pieces.append((line.project(shapely.Point(part.coords[0])), part))
        for _, part in sorted(pieces, key=lambda piece: piece[0]):
            parts_out.append(part)
            tags_out.append(tag_list[index] if tag_list is not None else None)
    return tuple(parts_out), tags_out


def _runs_backwards(part: LineString, source: LineString) -> bool:
    """Whether *part*, a piece of *source*, runs against it; a ring wraps at its start."""
    head = source.project(shapely.Point(part.coords[0]))
    ahead = source.project(part.interpolate(min(0.5 * part.length, 1.0e-3 * source.length)))
    advance = ahead - head
    if source.is_closed:
        advance %= source.length
        return advance > 0.5 * source.length
    return advance < 0.0

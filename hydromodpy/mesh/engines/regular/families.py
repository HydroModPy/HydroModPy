"""Line families on the regular grid: cell chains, staircase faces and sides.

A grid cannot follow a line. A ``cell`` family is rasterized with the thin-line
rule of WhiteboxTools (``line_crossing_cell_mask``) and ordered along the line.
A ``face`` family becomes a staircase: the cells are labeled by the polygon of
``domain boundary + family lines`` that holds their center, and the faces between
two labels are the family faces. A barrier line splits no polygon where it ends
inside the domain, so its staircase is the faces whose two cell centers lie
across it. The QA publishes how far that staircase is from the source lines.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from hydromodpy.mesh.cells.barrier_faces import crossed_edges
from hydromodpy.mesh.cells.crossed_by_lines import line_crossing_cell_mask
from hydromodpy.mesh.engines.regular.grid import GridLayout
from hydromodpy.mesh.planar.geometry import (
    BOX_SIDES,
    DerivedGeometry,
    cell_polygons,
)
from hydromodpy.mesh.planar.hydro_mesh import HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, FaceFamilyTable
from hydromodpy.mesh.request import BARRIER_FAMILY, LineFamilySpec

__all__ = ["FaceFamilies", "cell_chains", "face_family_columns"]

_WINDOW_MARGIN_CELLS = 2
"""Cells kept around a line when its crossing mask is computed on a sub-grid."""

_END_SNAP_REL = 1.0e-7
"""A line end this share of the domain span from the boundary is noded into it."""


@dataclass(frozen=True)
class FaceFamilies:
    """Face family columns, one row per face, and the zone each cell label carries."""

    table: FaceFamilyTable
    cell_zone: np.ndarray | None
    zone_names: tuple[str, ...]


def _window(line: LineString, layout: GridLayout) -> tuple[slice, slice]:
    """Rows and columns of the cells within a margin of the line, clipped to the grid."""
    minx, miny, maxx, maxy = line.bounds
    ytop = layout.yoff + layout.nrow * layout.dy
    margin = _WINDOW_MARGIN_CELLS
    c0 = int(np.floor((minx - layout.xoff) / layout.dx)) - margin
    c1 = int(np.ceil((maxx - layout.xoff) / layout.dx)) + margin
    r0 = int(np.floor((ytop - maxy) / layout.dy)) - margin
    r1 = int(np.ceil((ytop - miny) / layout.dy)) + margin
    return (
        slice(max(r0, 0), min(r1, layout.nrow)),
        slice(max(c0, 0), min(c1, layout.ncol)),
    )


def _chain_of_line(
    line: LineString,
    mesh: HydroMesh,
    centers: np.ndarray,
    layout: GridLayout,
    crs_wkt: str,
) -> np.ndarray:
    """Cell ids crossed by one oriented line, ordered by their first crossing."""
    rows, cols = _window(line, layout)
    if rows.start >= rows.stop or cols.start >= cols.stop:
        return np.empty(0, dtype=np.int64)
    ids = (
        np.arange(rows.start, rows.stop)[:, None] * layout.ncol
        + np.arange(cols.start, cols.stop)[None, :]
    ).reshape(-1)
    connectivity = np.asarray(mesh.flat_connectivity)[ids]
    polygons = cell_polygons(mesh.vertices, connectivity)
    crossed = line_crossing_cell_mask(
        polygons,
        mesh.vertices,
        connectivity,
        centers[ids],
        [line],
        mesh_crs=crs_wkt,
        geometry_crs=crs_wkt,
    ).mask
    cells = ids[crossed]
    if cells.size == 0:
        return cells.astype(np.int64)
    boxes = polygons[crossed]
    inside = shapely.intersection(boxes, line)
    coords, owner = shapely.get_coordinates(inside, return_index=True)
    # An intersection is empty when the cell was marked by the tie tolerance
    # alone; its first abscissa is then the one of its center.
    centre_s = shapely.line_locate_point(line, shapely.points(centers[cells]))
    first_s = centre_s.copy()
    if coords.size:
        along = shapely.line_locate_point(line, shapely.points(coords))
        first = np.full(cells.size, np.inf)
        np.minimum.at(first, owner, along)
        found = np.isfinite(first)
        first_s[found] = first[found]
    return cells[np.lexsort((centre_s, first_s))].astype(np.int64)


def cell_chains(
    spec: LineFamilySpec,
    mesh: HydroMesh,
    centers: np.ndarray,
    layout: GridLayout,
    crs_wkt: str,
    *,
    first_chain_id: int,
) -> list[CellChain]:
    """One chain per line of a ``cell`` family; a line that crosses no cell gives none."""
    chains: list[CellChain] = []
    for line in spec.lines:
        cells = _chain_of_line(line, mesh, centers, layout, crs_wkt)
        if cells.size:
            chains.append(CellChain(spec.name, first_chain_id + len(chains), cells))
    return chains


def boundary_columns(
    geometry: DerivedGeometry, layout: GridLayout
) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Per side, ``(cell, node_a, node_b)`` of the boundary faces on that side.

    The side is read from the grid columns and rows of the two nodes, exactly.
    """
    nx = layout.ncol + 1
    nodes = geometry.edge_nodes
    column = nodes % nx
    row = nodes // nx
    on_boundary = geometry.edge_cells[:, 1] < 0
    masks = {
        "west": (column == 0).all(axis=1),
        "east": (column == layout.ncol).all(axis=1),
        "south": (row == layout.nrow).all(axis=1),
        "north": (row == 0).all(axis=1),
    }
    out = {}
    for side in BOX_SIDES:
        keep = on_boundary & masks[side]
        out[side] = (
            geometry.edge_cells[keep, 0],
            nodes[keep, 0],
            nodes[keep, 1],
        )
    return out


def _noded_boundary(domain: Polygon, lines: tuple[LineString, ...]) -> BaseGeometry:
    """The domain boundary with the line ends that lie on it inserted as its vertices.

    A line clipped to the domain ends on the boundary only within rounding, so
    the union would not node it there and the line would split nothing.
    """
    minx, miny, maxx, maxy = domain.bounds
    tolerance = _END_SNAP_REL * max(maxx - minx, maxy - miny, 1.0)
    coords = [line.coords[k] for line in lines if not line.is_closed for k in (0, -1)]
    if not coords:
        return domain.boundary
    ends = shapely.points(coords)
    on_boundary = shapely.dwithin(ends, domain.boundary, tolerance)
    if not on_boundary.any():
        return domain.boundary
    return shapely.snap(domain.boundary, shapely.multipoints(ends[on_boundary]), tolerance)


def _cell_labels(centers: np.ndarray, domain: Polygon, lines: tuple[LineString, ...]) -> np.ndarray:
    """Index of the polygon of ``domain boundary + lines`` holding each center, ``-1`` if none."""
    pieces = list(polygonize(unary_union([_noded_boundary(domain, lines), *lines])))
    labels = np.full(len(centers), -1, dtype=np.int64)
    if not pieces:
        return labels
    point_index, piece_index = STRtree(pieces).query(
        shapely.points(centers), predicate="intersects"
    )
    order = np.lexsort((piece_index, point_index))
    point_index, piece_index = point_index[order], piece_index[order]
    first = np.ones(point_index.size, dtype=bool)
    first[1:] = point_index[1:] != point_index[:-1]
    labels[point_index[first]] = piece_index[first]
    return labels


def _side_of_line(
    line: LineString, midpoints: np.ndarray, first: np.ndarray, second: np.ndarray
) -> np.ndarray:
    """Whether the first cell is on the left of the oriented line, per face."""
    along = shapely.line_locate_point(line, shapely.points(midpoints))
    step = 1.0e-6 * max(line.length, 1.0)
    before = shapely.line_interpolate_point(line, np.maximum(along - step, 0.0))
    after = shapely.line_interpolate_point(line, np.minimum(along + step, line.length))
    foot = shapely.line_interpolate_point(line, along)
    tangent = shapely.get_coordinates(after) - shapely.get_coordinates(before)
    origin = shapely.get_coordinates(foot)
    return _left_turn(tangent, origin, first) > _left_turn(tangent, origin, second)


def _left_turn(tangent: np.ndarray, origin: np.ndarray, point: np.ndarray) -> np.ndarray:
    """Cross product of the tangent with the offset of each point from its foot on the line."""
    offset = point - origin
    return tangent[:, 0] * offset[:, 1] - tangent[:, 1] * offset[:, 0]


def face_family_columns(
    specs: list[LineFamilySpec],
    domain: Polygon,
    geometry: DerivedGeometry,
    centers: np.ndarray,
    layout: GridLayout,
) -> FaceFamilies:
    """The face family table: the sides, then the staircase of every ``face`` family.

    ``specs`` are the ``face`` families. A row puts on ``cell_a`` the cell on the
    left of the nearest source line; its zones are those of that line.
    """
    zone_names: list[str] = []
    for spec in specs:
        for name in (*spec.zone_left, *spec.zone_right):
            if name not in zone_names:
                zone_names.append(name)

    families: list[tuple[str, dict[str, np.ndarray]]] = [
        (
            f"boundary:{side}",
            {"cell_a": cell, "cell_b": np.full(cell.size, -1), "node_a": a, "node_b": b},
        )
        for side, (cell, a, b) in boundary_columns(geometry, layout).items()
    ]
    no_row = {key: np.empty(0, dtype=np.int64) for key in ("cell_a", "cell_b", "node_a", "node_b")}

    cell_zone: np.ndarray | None = None
    for spec in specs:
        labels, stairs = _staircase_edges(spec, domain, geometry, centers)
        if stairs.size == 0 or not spec.lines:
            families.append((spec.name, no_row))
            continue
        rows = _staircase_rows(spec, stairs, geometry, centers, zone_names)
        families.append((spec.name, rows))
        if cell_zone is None and zone_names and spec.zone_left:
            cell_zone = _label_zones(
                labels,
                labels[rows["cell_a"]],
                labels[rows["cell_b"]],
                rows["zone_left"],
                rows["zone_right"],
            )

    return FaceFamilies(FaceFamilyTable.stack(families), cell_zone, tuple(zone_names))


def _staircase_edges(
    spec: LineFamilySpec, domain: Polygon, geometry: DerivedGeometry, centers: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The polygon label of each cell and the sorted edge ids of the staircase of one family.

    The barrier family labels no cell: its staircase is the edges whose two cell
    centers lie across one of its lines. Any other family labels each cell by the
    polygon of ``domain boundary + lines`` holding its center, and its staircase
    is the interior edges between two labels.
    """
    pair = geometry.edge_cells
    if spec.name == BARRIER_FAMILY:
        labels = np.full(len(centers), -1, dtype=np.int64)
        stairs = np.unique(
            np.concatenate(
                [crossed_edges(geometry, centers, line) for line in spec.lines]
                or [np.empty(0, dtype=np.int64)]
            )
        )
        return labels, stairs
    labels = _cell_labels(centers, domain, spec.lines)
    label_a = labels[np.maximum(pair[:, 0], 0)]
    label_b = labels[np.maximum(pair[:, 1], 0)]
    interior = pair[:, 1] >= 0
    stairs = np.flatnonzero(interior & (label_a >= 0) & (label_b >= 0) & (label_a != label_b))
    return labels, stairs


def _staircase_rows(
    spec: LineFamilySpec,
    stairs: np.ndarray,
    geometry: DerivedGeometry,
    centers: np.ndarray,
    zone_names: list[str],
) -> dict[str, np.ndarray]:
    """The table columns of the staircase edges ``stairs`` of one family.

    Each edge goes to its nearest source line. ``cell_a`` is the cell on the
    left of that line and the zones are the ones that line carries.
    """
    first = geometry.edge_cells[stairs, 0]
    second = geometry.edge_cells[stairs, 1]
    midpoints = geometry.edge_midpoint[stairs]
    line_of = STRtree(list(spec.lines)).nearest(shapely.points(midpoints))
    first_is_left = np.zeros(stairs.size, dtype=bool)
    for line_index in np.unique(line_of):
        rows = line_of == line_index
        first_is_left[rows] = _side_of_line(
            spec.lines[line_index], midpoints[rows], centers[first[rows]], centers[second[rows]]
        )
    return {
        "cell_a": np.where(first_is_left, first, second),
        "cell_b": np.where(first_is_left, second, first),
        "node_a": geometry.edge_nodes[stairs, 0],
        "node_b": geometry.edge_nodes[stairs, 1],
        "zone_left": _zone_ids(spec.zone_left, line_of, zone_names),
        "zone_right": _zone_ids(spec.zone_right, line_of, zone_names),
    }


def _zone_ids(zones: tuple[str, ...], line_of: np.ndarray, zone_names: list[str]) -> np.ndarray:
    """Zone index of the nearest line of each face; ``-1`` when the family names no zone."""
    if not zones:
        return np.full(line_of.size, -1, dtype=np.int32)
    ids = np.array([zone_names.index(name) for name in zones], dtype=np.int32)
    return ids[line_of]


def _label_zones(
    labels: np.ndarray,
    label_left: np.ndarray,
    label_right: np.ndarray,
    zone_left: np.ndarray,
    zone_right: np.ndarray,
) -> np.ndarray:
    """Zone of each cell: the first zone the faces bordering its polygon give it, else ``-1``."""
    seen_labels = np.concatenate([label_left, label_right])
    seen_zones = np.concatenate([zone_left, zone_right])
    named = seen_zones >= 0
    seen_labels, seen_zones = seen_labels[named], seen_zones[named]
    by_label = np.full(int(labels.max()) + 1 if labels.size else 0, -1, dtype=np.int32)
    unique_labels, first = np.unique(seen_labels, return_index=True)
    by_label[unique_labels] = seen_zones[first]
    return np.where(labels >= 0, by_label[np.maximum(labels, 0)], -1).astype(np.int32)

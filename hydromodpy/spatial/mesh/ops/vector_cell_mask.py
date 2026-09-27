"""Project a vector layer onto mesh cells (mesh-agnostic).

Vector twin of :mod:`~hydromodpy.spatial.mesh.ops.zonal_stats`: instead of
reducing raster pixels onto cells, it answers which cells a linework (or any
geometry set) reaches. A LINEWORK reaches every cell its geometry touches,
never only the cells whose centre it contains: on a Voronoi mesh the centroid
rule drops roughly half the cells of a one-cell-wide line, and any distance
measured from a mask that thin is biased by half a cell.

An AREAL layer takes the opposite rule, ``rule="centroid"``, because touch
inclusion adds a full exterior ring of cells that lie mostly outside the
polygon. The two rules are the ``all_touched`` choice the raster path already
makes for the same pair of objects, in
:mod:`~hydromodpy.spatial.geographic.core.stream_dem_agreement`, where the
network is rasterized with ``all_touched=True`` and the catchment with
``all_touched=False``.

A mapped stream network fed to the stream-network criterion takes a third
rule, :func:`line_crossing_cell_mask`: the thin line WhiteboxTools
``VectorLinesToRaster`` draws, restated on the face graph of any mesh so a
Voronoi mesh gets the same rule as a grid.

Both CRS are mandatory arguments. Neither mesh container in the repository
carries one (``HydroMesh`` and the persisted UGRID mesh both store bare
coordinates), so a caller that cannot name them is overlaying two frames it has
never checked.

The functions take bare arrays rather than a mesh class: the same projection
serves ``HydroMesh.flat_connectivity`` (ragged) and the persisted
``face_node_connectivity`` (dense, negative-padded), and ``spatial`` cannot
import the layer that owns the second one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from pyproj import CRS
    from shapely.geometry.base import BaseGeometry

    CrsLike = str | int | CRS

CellMaskRule = Literal["touch", "centroid"]

__all__ = [
    "CellMaskRule",
    "LineCrossingMask",
    "cell_polygons",
    "line_crossing_cell_mask",
    "vector_cell_mask",
]

_TIE_TOLERANCE_M = 1.0e-6
"""Distance under which a crossing point counts as lying on a cell edge.

A crossing computed in floating point lands a few ulps off the edge it should
sit on; at Lambert-93 magnitudes that is about 1e-9 m. One micrometre catches
those and nothing a map can resolve.
"""


def cell_polygons(
    vertices: np.ndarray,
    connectivity: np.ndarray | Sequence[np.ndarray],
) -> np.ndarray:
    """Return one Shapely polygon per mesh cell, ``None`` where the cell is degenerate.

    Ragged-safe: a dense ``(n_cells, k)`` array padded with negative indices and
    a per-cell sequence of node arrays are both accepted.
    """
    import shapely
    from shapely.geometry import Polygon

    points = np.asarray(vertices, dtype=float)[:, :2]
    n_nodes = points.shape[0]

    dense = _dense_rows(connectivity, n_nodes=n_nodes)
    if dense is not None:
        return _polygons_from_dense_rows(points, dense)

    polygons: list[Polygon | None] = []
    for row in connectivity:
        nodes = _clean_row(row, n_nodes=n_nodes)
        if nodes.size < 3:
            polygons.append(None)
            continue
        polygon = shapely.polygons(points[nodes])
        polygons.append(polygon if polygon.is_valid and not polygon.is_empty else None)
    return np.asarray(polygons, dtype=object)


def _clean_row(row: object, *, n_nodes: int) -> np.ndarray:
    """Return the valid node indices of one cell, padding and NaNs dropped."""
    nodes = np.asarray(row).reshape(-1)
    if nodes.dtype.kind == "f":
        nodes = nodes[np.isfinite(nodes)]
    nodes = nodes.astype(int)
    return nodes[(nodes >= 0) & (nodes < n_nodes)]


def _dense_rows(
    connectivity: np.ndarray | Sequence[np.ndarray], *, n_nodes: int
) -> np.ndarray | None:
    """Return a rectangular, fully valid index table, or ``None`` when ragged.

    The fast path needs every cell to hold the same number of usable nodes; a
    Voronoi dual does not, and falls back to the per-cell loop.
    """
    # A genuinely ragged sequence raises in numpy 2, so only an array that is
    # already rectangular is even looked at.
    if not isinstance(connectivity, np.ndarray):
        return None
    table = connectivity
    if table.ndim != 2 or table.shape[1] < 3 or table.dtype.kind not in "iu":
        return None
    if not np.all((table >= 0) & (table < n_nodes)):
        return None
    return table


def _polygons_from_dense_rows(points: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Build every polygon of a rectangular table in one vectorised call.

    Shapely 2 builds an array of polygons from an ``(n_cells, k, 2)`` coordinate
    block in C. Doing it cell by cell costs six Python-level shapely calls per
    cell: measured on the Nancon at 25 m, 243 552 cells took 14.6 s that way and
    0.5 s this way, and that time was paid by every figure of every gallery.
    """
    import shapely

    coords = points[rows]
    polygons = shapely.polygons(coords)
    usable = shapely.is_valid(polygons) & ~shapely.is_empty(polygons)
    result = np.asarray(polygons, dtype=object)
    result[~usable] = None
    return result


def vector_cell_mask(
    polygons: np.ndarray,
    geometries: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
    distance_m: float = 0.0,
    rule: CellMaskRule = "touch",
) -> np.ndarray:
    """Boolean per-cell mask of the cells one vector layer reaches.

    ``polygons`` comes from :func:`cell_polygons`; it is an argument rather than
    an internal step because a caller that also needs cell centroids or areas
    already holds it, and rebuilding it costs about a second on a large mesh.

    ``rule`` says what "reaches" means. ``"touch"`` keeps every cell the
    geometry intersects, the rule a linework needs. ``"centroid"`` keeps the
    cells whose centre the geometry contains, the rule an areal layer needs: a
    catchment taken by touch is the delineated basin plus one exterior ring, and
    that ring is measured by whatever is averaged over the mask.

    ``distance_m`` widens the test to every cell within that distance of a
    geometry. It is a ``dwithin`` predicate, never a buffer: buffering the
    linework would also enlarge the geometry a caller then measures distances
    against, which is a different question. It applies to ``"touch"`` only;
    widening a centroid rule by a distance is two rules at once and is refused.
    """
    from shapely.strtree import STRtree

    if rule not in ("touch", "centroid"):
        raise ValueError(f"rule must be 'touch' or 'centroid', got {rule!r}.")
    if rule == "centroid" and float(distance_m) > 0.0:
        raise ValueError(
            "distance_m widens a touch rule; combining it with rule='centroid' asks for a "
            "cell whose centre is inside AND whose polygon is within a distance, which are "
            "two different masks. Pick one."
        )

    mask = np.zeros(polygons.shape[0], dtype=bool)

    parts = _to_mesh_crs(geometries, mesh_crs=mesh_crs, geometry_crs=geometry_crs)
    if not parts:
        return mask

    usable = np.array([polygon is not None for polygon in polygons], dtype=bool)
    if not usable.any():
        return mask

    kept = list(polygons[usable])
    query = np.empty(len(parts), dtype=object)
    query[:] = parts
    if rule == "centroid":
        # The tree holds the cell centres, so "the geometry contains the cell"
        # is exactly the raster ``all_touched=False`` rule.
        tree = STRtree([polygon.centroid for polygon in kept])
        hits = tree.query(query, predicate="contains")
    elif float(distance_m) > 0.0:
        tree = STRtree(kept)
        hits = tree.query(query, predicate="dwithin", distance=float(distance_m))
    else:
        tree = STRtree(kept)
        hits = tree.query(query, predicate="intersects")
    if hits.size:
        mask[np.flatnonzero(usable)[np.unique(hits[1])]] = True
    return mask


@dataclass(frozen=True)
class LineCrossingMask:
    """The cells a linework crosses, and how many reaches needed the fallback.

    ``n_fallback_parts`` counts the line parts that crossed no centre-to-centre
    segment and were given the cell holding their midpoint instead.
    WhiteboxTools drops such a reach; here no mapped reach that reaches the
    mesh disappears, and the count says how often that departure applied.

    ``n_outside_parts`` counts the line parts that cross no segment and touch
    no usable cell polygon: they lie wholly off the mesh, in a sliver between
    the clip polygon and the cells, for instance. No cell holds them, so they
    are left out of the mask, and the count lets the caller say so.
    """

    mask: np.ndarray
    n_fallback_parts: int
    n_outside_parts: int


def line_crossing_cell_mask(
    polygons: np.ndarray,
    vertices: np.ndarray,
    face_node_connectivity: np.ndarray | Sequence[np.ndarray],
    centres: np.ndarray,
    geometries: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
    active: np.ndarray | None = None,
) -> LineCrossingMask:
    """Mask of the cells holding a point where a line crosses the face graph.

    The face graph joins the centres of every two cells that share an edge. A
    cell belongs to the line when it contains a point where the line crosses
    one of those segments. On a regular grid the segments are the cell medians,
    and this is exactly WhiteboxTools ``VectorLinesToRaster``, the tool of
    Abherve et al. (2023): a cell is marked when the line crosses one of its
    two medians. The result is a thin line, neither Bresenham nor all-touched.

    Why thin. The stream-network criterion compares two mean distances whose
    zero is their equality. The simulated network is a chain of the descent
    graph, one cell wide. A mapped network drawn thicker than that chain moves
    the zero with no hydrogeological reason: a model that reproduces the map
    exactly scores J < 0 under the touch rule, whose diagonal steps add the two
    cells sharing the corner. Under this rule the polyline of a chain's centres
    crosses the face graph only at those centres, and gives the chain back.

    ``centres`` are the points the criterion samples the top at, the generator
    seeds of a Voronoi mesh rather than its polygon centroids. A boundary cell
    also joins its centre to the midpoint of each unshared edge, the half
    median WhiteboxTools draws up to the raster border.

    Ties are conservative: a crossing on an edge marks both cells, a crossing
    on a node every cell around it. A line part that crosses no segment (a
    reach shorter than about half a cell, or held in a corner) marks the cell
    holding its midpoint. When that midpoint lies off the mesh, the part keeps
    the cell it enters nearest to the midpoint. A part that enters no usable
    cell is counted in ``n_outside_parts`` and marks nothing: snapping it to
    the nearest boundary cell would draw a stream the model domain does not
    hold. ``active`` is applied last.
    """
    import shapely
    from shapely.strtree import STRtree

    n_cells = int(polygons.shape[0])
    mask = np.zeros(n_cells, dtype=bool)
    points = np.asarray(centres, dtype=float)[:, :2]
    if points.shape[0] != n_cells:
        raise ValueError(f"centres holds {points.shape[0]} point(s) for {n_cells} cell polygon(s).")

    parts = _line_parts(_to_mesh_crs(geometries, mesh_crs=mesh_crs, geometry_crs=geometry_crs))
    usable = np.array([polygon is not None for polygon in polygons], dtype=bool)
    usable &= np.isfinite(points).all(axis=1)
    if not parts or not usable.any():
        return LineCrossingMask(mask=mask, n_fallback_parts=0, n_outside_parts=len(parts))

    graph = _face_graph_segments(
        np.asarray(vertices, dtype=float)[:, :2], face_node_connectivity, points, usable=usable
    )
    cell_index = np.flatnonzero(usable)
    cell_tree = STRtree(polygons[usable])

    coords, owner = shapely.get_coordinates(np.asarray(parts, dtype=object), return_index=True)
    same_part = owner[:-1] == owner[1:]
    pieces = shapely.linestrings(np.stack([coords[:-1][same_part], coords[1:][same_part]], axis=1))
    piece_part = owner[:-1][same_part]

    marked_parts = np.zeros(len(parts), dtype=bool)
    if graph.size and pieces.size:
        piece_hit, graph_hit = STRtree(graph).query(pieces, predicate="intersects")
        crossings = shapely.intersection(pieces[piece_hit], graph[graph_hit])
        # A Point stays a point; a MultiPoint splits; a line lying on a
        # segment keeps its two ends, which is what the vertices give.
        xy, which = shapely.get_coordinates(crossings, return_index=True)
        if xy.size:
            point_hit, cell_hit = cell_tree.query(
                shapely.points(xy), predicate="dwithin", distance=_TIE_TOLERANCE_M
            )
            mask[cell_index[cell_hit]] = True
            marked_parts[piece_part[piece_hit[which[point_hit]]]] = True

    missing = np.flatnonzero(~marked_parts)
    n_fallback = 0
    n_outside = 0
    if missing.size:
        missing_parts = np.asarray(parts, dtype=object)[missing]
        midpoints = shapely.line_interpolate_point(missing_parts, 0.5, normalized=True)
        point_hit, cell_hit = cell_tree.query(
            midpoints, predicate="dwithin", distance=_TIE_TOLERANCE_M
        )
        mask[cell_index[cell_hit]] = True
        held = np.zeros(missing.size, dtype=bool)
        held[point_hit] = True
        # A part whose midpoint falls off the mesh but whose line still
        # enters it keeps the cell it enters nearest to that midpoint.
        stray = np.flatnonzero(~held)
        if stray.size:
            part_hit, polygon_hit = cell_tree.query(missing_parts[stray], predicate="intersects")
            if part_hit.size:
                distance = shapely.distance(
                    cell_tree.geometries[polygon_hit], midpoints[stray][part_hit]
                )
                order = np.lexsort((distance, part_hit))
                first = np.ones(order.size, dtype=bool)
                first[1:] = part_hit[order][1:] != part_hit[order][:-1]
                mask[cell_index[polygon_hit[order][first]]] = True
                held[stray[np.unique(part_hit)]] = True
        n_fallback = int(held.sum())
        n_outside = int(missing.size - n_fallback)

    if active is not None:
        mask &= np.asarray(active, dtype=bool).reshape(-1)
    return LineCrossingMask(mask=mask, n_fallback_parts=n_fallback, n_outside_parts=n_outside)


def _line_parts(geometries: Sequence[BaseGeometry]) -> list[BaseGeometry]:
    """Split multi-part and collection geometries into their non-empty lines."""
    import shapely

    parts: list[BaseGeometry] = []
    for geometry in geometries:
        for part in shapely.get_parts(geometry):
            if part.geom_type in ("MultiLineString", "GeometryCollection"):
                parts.extend(_line_parts([part]))
                continue
            if part.geom_type not in ("LineString", "LinearRing"):
                raise ValueError(f"the crossing rule rasterizes lines; got a {part.geom_type}.")
            if not part.is_empty and part.length > 0.0:
                parts.append(part)
    return parts


def _face_graph_segments(
    vertices: np.ndarray,
    connectivity: np.ndarray | Sequence[np.ndarray],
    centres: np.ndarray,
    *,
    usable: np.ndarray,
) -> np.ndarray:
    """Return the centre-to-centre segments of the face graph as Shapely lines.

    One segment per pair of usable cells sharing an edge, plus, for an edge no
    other usable cell shares, the half segment from the centre to the edge
    midpoint.
    """
    import shapely

    rows = _padded_rows(connectivity, n_nodes=vertices.shape[0])
    n_cells = min(rows.shape[0], usable.size)
    rows = rows[:n_cells]
    present = rows >= 0
    ring = np.take_along_axis(rows, np.argsort(~present, axis=1, kind="stable"), axis=1)
    arity = present.sum(axis=1)
    slots = np.arange(rows.shape[1])
    following = np.take_along_axis(
        ring, np.mod(slots[None, :] + 1, np.maximum(arity, 1)[:, None]), axis=1
    )
    low = np.minimum(ring, following)
    high = np.maximum(ring, following)
    drawn = (slots[None, :] < arity[:, None]) & usable[:n_cells, None] & (low != high)

    owner = np.broadcast_to(np.arange(n_cells)[:, None], rows.shape)[drawn]
    low, high = low[drawn], high[drawn]
    order = np.lexsort((owner, high, low))
    owner, low, high = owner[order], low[order], high[order]
    same_edge = (low[1:] == low[:-1]) & (high[1:] == high[:-1])
    first, second = owner[:-1][same_edge], owner[1:][same_edge]
    pairs = np.unique(np.column_stack([first, second]), axis=0) if first.size else first
    shared = np.zeros(owner.size, dtype=bool)
    shared[1:] |= same_edge
    shared[:-1] |= same_edge

    starts: list[np.ndarray] = []
    ends: list[np.ndarray] = []
    if len(pairs):
        pairs = pairs[pairs[:, 0] != pairs[:, 1]]
        starts.append(centres[pairs[:, 0]])
        ends.append(centres[pairs[:, 1]])
    if (~shared).any():
        starts.append(centres[owner[~shared]])
        ends.append(0.5 * (vertices[low[~shared]] + vertices[high[~shared]]))
    if not starts:
        return np.empty(0, dtype=object)
    return shapely.linestrings(np.stack([np.concatenate(starts), np.concatenate(ends)], axis=1))


def _padded_rows(connectivity: np.ndarray | Sequence[np.ndarray], *, n_nodes: int) -> np.ndarray:
    """Return the connectivity as one integer table, missing slots set to -1."""
    if isinstance(connectivity, np.ndarray) and connectivity.ndim == 2:
        table = connectivity
        if table.dtype.kind == "f":
            table = np.where(np.isfinite(table), table, -1)
        table = table.astype(np.int64)
        return np.where((table >= 0) & (table < n_nodes), table, -1)
    rows = [_clean_row(row, n_nodes=n_nodes) for row in connectivity]
    width = max((row.size for row in rows), default=0)
    table = np.full((len(rows), width), -1, dtype=np.int64)
    for index, row in enumerate(rows):
        table[index, : row.size] = row
    return table


def _to_mesh_crs(
    geometries: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
) -> list[BaseGeometry]:
    """Return the non-empty geometries expressed in the mesh CRS."""
    from pyproj import Transformer
    from shapely.ops import transform

    target = _require_crs(mesh_crs, "mesh_crs")
    source = _require_crs(geometry_crs, "geometry_crs")
    parts = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not parts or source.equals(target):
        return parts
    project = Transformer.from_crs(source, target, always_xy=True).transform
    return [transform(project, geometry) for geometry in parts]


def _require_crs(crs_like: CrsLike | None, name: str) -> CRS:
    """Coerce one CRS argument, refusing the missing case."""
    from pyproj import CRS

    if crs_like is None or (isinstance(crs_like, str) and not crs_like.strip()):
        raise ValueError(
            f"vector_cell_mask needs an explicit {name}: a mesh stores bare coordinates, "
            "so without both frames the overlay silently compares two different ones."
        )
    return CRS.from_user_input(crs_like)

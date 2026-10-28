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

An areal layer that weights a total rather than selecting cells takes
:func:`cell_area_fraction`, the share of each cell's area inside the layer.
It is the area-weighted overlay GSFLOW uses to map its HRUs onto the cells: a
cell field integrated with these weights is the integral of that field over
the polygon, where a centroid mask counts a boundary cell whole or not at all.

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

from hydromodpy.spatial.geographic.core.network_heads import line_parts
from hydromodpy.spatial.mesh.model.derived_geometry import padded_rows

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.core.io.crs import CrsLike

CellMaskRule = Literal["touch", "centroid"]

__all__ = [
    "CellMaskRule",
    "LineCrossingMask",
    "cell_area_fraction",
    "line_crossing_cell_mask",
    "vector_cell_mask",
]

_TIE_TOLERANCE_M = 1.0e-6
"""Distance under which a crossing point counts as lying on a cell edge.

A crossing computed in floating point lands a few ulps off the edge it should
sit on; at Lambert-93 magnitudes that is about 1e-9 m. One micrometre catches
those and nothing a map can resolve.
"""


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

    ``polygons`` comes from
    :func:`~hydromodpy.spatial.mesh.model.derived_geometry.cell_polygons`; it is an argument rather than
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

    from hydromodpy.core.io.crs import to_mesh_crs

    if rule not in ("touch", "centroid"):
        raise ValueError(f"rule must be 'touch' or 'centroid', got {rule!r}.")
    if rule == "centroid" and float(distance_m) > 0.0:
        raise ValueError(
            "distance_m widens a touch rule; combining it with rule='centroid' asks for a "
            "cell whose centre is inside AND whose polygon is within a distance, which are "
            "two different masks. Pick one."
        )

    mask = np.zeros(polygons.shape[0], dtype=bool)

    parts = to_mesh_crs(geometries, mesh_crs=mesh_crs, geometry_crs=geometry_crs)
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


def cell_area_fraction(
    polygons: np.ndarray,
    geometries: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
) -> np.ndarray:
    """Share of each cell's area inside an areal layer, in [0, 1].

    ``polygons`` comes from
    :func:`~hydromodpy.spatial.mesh.model.derived_geometry.cell_polygons`. A cell the layer contains
    gets 1, a cell it misses gets 0, and a cell its outline crosses gets the
    area of the intersection over the area of the cell. Only the crossed
    cells pay for an intersection. A degenerate cell (``None``) gets 0.
    """
    import shapely

    from hydromodpy.core.io.crs import to_mesh_crs

    fraction = np.zeros(polygons.shape[0], dtype=float)
    parts = to_mesh_crs(geometries, mesh_crs=mesh_crs, geometry_crs=geometry_crs)
    if not parts:
        return fraction
    region = shapely.union_all(parts)
    if region.is_empty:
        return fraction
    usable = np.flatnonzero(np.array([polygon is not None for polygon in polygons], dtype=bool))
    if not usable.size:
        return fraction
    cells = np.asarray(polygons[usable], dtype=object)
    shapely.prepare(region)
    inside = shapely.contains(region, cells)
    crossed = ~inside & shapely.intersects(region, cells)
    fraction[usable[inside]] = 1.0
    if np.any(crossed):
        cut = cells[crossed]
        area = shapely.area(cut)
        shared = shapely.area(shapely.intersection(cut, region))
        with np.errstate(divide="ignore", invalid="ignore"):
            share = np.where(area > 0.0, shared / area, 0.0)
        fraction[usable[crossed]] = np.clip(share, 0.0, 1.0)
    return fraction


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

    from hydromodpy.core.io.crs import to_mesh_crs

    n_cells = int(polygons.shape[0])
    mask = np.zeros(n_cells, dtype=bool)
    points = np.asarray(centres, dtype=float)[:, :2]
    if points.shape[0] != n_cells:
        raise ValueError(f"centres holds {points.shape[0]} point(s) for {n_cells} cell polygon(s).")

    parts = line_parts(to_mesh_crs(geometries, mesh_crs=mesh_crs, geometry_crs=geometry_crs))
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

    rows = padded_rows(connectivity, n_nodes=vertices.shape[0])
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

"""Project a vector layer onto mesh cells (mesh-agnostic).

Vector twin of :mod:`~hydromodpy.spatial.mesh.cells.zonal_stats`: instead of
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
rule, the thin line of
:func:`~hydromodpy.spatial.mesh.cells.crossed_by_lines.line_crossing_cell_mask`.

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
serves ``HydroMesh.flat_connectivity`` and the persisted
``face_node_connectivity`` (both dense, negative-padded), and ``spatial`` cannot
import the layer that owns the second one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.core.io.crs import CrsLike

__all__ = ["CellMaskRule", "cell_area_fraction", "vector_cell_mask"]

CellMaskRule = Literal["touch", "centroid"]


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
    :func:`~hydromodpy.spatial.mesh.model.geometry.cell_polygons`; it is an argument rather than
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
    :func:`~hydromodpy.spatial.mesh.model.geometry.cell_polygons`. A cell the layer contains
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

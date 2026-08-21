"""Project a vector layer onto mesh cells (mesh-agnostic).

Vector twin of :mod:`~hydromodpy.spatial.mesh.ops.zonal_stats`: instead of
reducing raster pixels onto cells, it answers which cells a linework (or any
geometry set) reaches. A cell belongs to the layer when the geometry intersects
its polygon, never when it merely contains the cell centre: on a Voronoi mesh
the centroid rule drops roughly half the cells of a one-cell-wide line, and any
distance measured from a mask that thin is biased by half a cell.

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
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pyproj import CRS
    from shapely.geometry.base import BaseGeometry

    CrsLike = str | int | CRS

__all__ = ["cell_polygons", "vector_cell_mask"]


def cell_polygons(
    vertices: np.ndarray,
    connectivity: np.ndarray | Sequence[np.ndarray],
) -> np.ndarray:
    """Return one Shapely polygon per mesh cell, ``None`` where the cell is degenerate.

    Ragged-safe: a dense ``(n_cells, k)`` array padded with negative indices and
    a per-cell sequence of node arrays are both accepted.
    """
    from shapely.geometry import Polygon

    points = np.asarray(vertices, dtype=float)[:, :2]
    n_nodes = points.shape[0]
    polygons: list[Polygon | None] = []
    for row in connectivity:
        nodes = np.asarray(row).reshape(-1)
        if nodes.dtype.kind == "f":
            nodes = nodes[np.isfinite(nodes)]
        nodes = nodes.astype(int)
        nodes = nodes[(nodes >= 0) & (nodes < n_nodes)]
        if nodes.size < 3:
            polygons.append(None)
            continue
        polygon = Polygon(points[nodes])
        polygons.append(polygon if polygon.is_valid and not polygon.is_empty else None)
    return np.asarray(polygons, dtype=object)


def vector_cell_mask(
    polygons: np.ndarray,
    geometries: Sequence[BaseGeometry],
    *,
    mesh_crs: CrsLike,
    geometry_crs: CrsLike,
    distance_m: float = 0.0,
) -> np.ndarray:
    """Boolean per-cell mask of the cells one vector layer reaches.

    ``polygons`` comes from :func:`cell_polygons`; it is an argument rather than
    an internal step because a caller that also needs cell centroids or areas
    already holds it, and rebuilding it costs about a second on a large mesh.

    ``distance_m`` widens the test to every cell within that distance of a
    geometry. It is a ``dwithin`` predicate, never a buffer: buffering the
    linework would also enlarge the geometry a caller then measures distances
    against, which is a different question.
    """
    from shapely.strtree import STRtree

    mask = np.zeros(polygons.shape[0], dtype=bool)

    parts = _to_mesh_crs(geometries, mesh_crs=mesh_crs, geometry_crs=geometry_crs)
    if not parts:
        return mask

    usable = np.array([polygon is not None for polygon in polygons], dtype=bool)
    if not usable.any():
        return mask

    tree = STRtree(list(polygons[usable]))
    query = np.empty(len(parts), dtype=object)
    query[:] = parts
    if float(distance_m) > 0.0:
        hits = tree.query(query, predicate="dwithin", distance=float(distance_m))
    else:
        hits = tree.query(query, predicate="intersects")
    if hits.size:
        mask[np.flatnonzero(usable)[np.unique(hits[1])]] = True
    return mask


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

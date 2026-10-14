"""Voronoi / PEBI dual mesh of a set of seed points, clipped to a domain.

Turn a set of seed points (typically the vertices of a triangulation) plus a
domain polygon into a Voronoi (perpendicular-bisector) planar
:class:`~hydromodpy.spatial.mesh.model.hydro_mesh.HydroMesh`. The cell center is
the seed, so the DISV grid is exactly K-orthogonal for the two-point flux (TPFA).

The cells are built in a local frame, centred near the domain: Qhull and GEOS lose
digits on Lambert-93 coordinates, and two seeds a few metres apart can give two
identical cells. Refinement and constraint conformance come entirely from the seed
placement; this module only builds the dual and clips it to the domain.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import MultiPolygon, Polygon

from hydromodpy.spatial.mesh.engines.voronoi.frame import local_frame
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    cell_topology,
    voronoi_cells,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

__all__ = [
    "voronoi_planar_mesh",
    "domain_polygon_from_mesh",
]


def voronoi_planar_mesh(seeds: np.ndarray, domain_polygon: Polygon | MultiPolygon) -> HydroMesh:
    """Build a ragged-polygon planar ``HydroMesh`` (Voronoi/PEBI dual).

    Cell centers are stored as ``cell_data["disv_cell_center"]`` (the seeds), so
    the DISV export writes exact perpendicular-bisector cell centers. Cell
    corners closer than 1 mm are one vertex. A seed whose cell has no part inside
    the domain, or two coincident seeds, raise ``MeshGenerationError``.
    """
    seeds = np.asarray(seeds, dtype=float)
    if seeds.ndim != 2 or seeds.shape[1] != 2:
        raise ValueError(f"seeds must have shape (n, 2), got {seeds.shape}")
    frame = local_frame(domain_polygon)
    domain = frame.to_local(domain_polygon)
    cells = voronoi_cells(frame.to_local(seeds), domain, voronoi_envelope(domain, 0.0))
    topology = cell_topology(cells, frame)
    return HydroMesh(
        vertices=frame.to_world(topology.vertices),
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=topology.rings),),
        cell_data={"disv_cell_center": seeds},
    )


def domain_polygon_from_mesh(planar_mesh: HydroMesh) -> Polygon | MultiPolygon:
    """Reconstruct the meshed-domain outline from a planar mesh's boundary edges.

    A boundary edge belongs to exactly one cell; polygonizing those edges yields
    the outer polygon (with interior holes), which clips the Voronoi boundary
    cells. Works for any cell arity (triangles, quads, or n-gons).
    """
    from collections import defaultdict

    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    verts = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    edge_count: dict[tuple[int, int], int] = defaultdict(int)
    for cell in planar_mesh.flat_connectivity:
        cell = np.asarray(cell, dtype=int)
        k = len(cell)
        for i in range(k):
            a, b = int(cell[i]), int(cell[(i + 1) % k])
            edge_count[(min(a, b), max(a, b))] += 1
    lines = [LineString([verts[a], verts[b]]) for (a, b), n in edge_count.items() if n == 1]
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        raise ValueError("could not reconstruct a domain polygon from mesh boundary edges")
    outer = max(polys, key=lambda p: p.area)
    holes = [p for p in polys if p is not outer and outer.contains(p.representative_point())]
    if holes:
        outer = Polygon(outer.exterior.coords, [h.exterior.coords for h in holes])
    return outer

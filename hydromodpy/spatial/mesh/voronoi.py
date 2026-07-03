"""Voronoi / PEBI dual mesh generation for MODFLOW 6 DISV.

Turn a set of seed points (typically the vertices of a refined, constraint-
conforming triangulation) plus a domain polygon into a Voronoi (perpendicular-
bisector) planar :class:`~hydromodpy.spatial.mesh.hydro_mesh.HydroMesh`. The
cell center is the seed, so the DISV grid is exactly K-orthogonal for the
two-point flux (TPFA): the numerically optimal CVFD grid for isotropic
conductivity, with no XT3D needed.

Refinement and constraint conformance come entirely from the seed placement
(reused from the existing gmsh pipeline). This module only builds the dual and
clips it to the domain; it is agnostic to the solver and to what is modelled.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon

from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh

__all__ = [
    "voronoi_cells",
    "voronoi_planar_mesh",
    "voronoi_dual_of_mesh",
    "domain_polygon_from_mesh",
]


def _finite_regions(vor: Voronoi, radius: float) -> list[np.ndarray]:
    """Reconstruct finite Voronoi cell polygons, extending open ridges to ``radius``.

    scipy leaves boundary cells open (a ``-1`` vertex); we project each open
    ridge outward by ``radius`` so every cell becomes a finite polygon that the
    caller then clips to the real domain.
    """
    center = vor.points.mean(axis=0)
    ridges: dict[int, list[tuple[int, int, int]]] = {}
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices, strict=True):
        ridges.setdefault(p1, []).append((p2, v1, v2))
        ridges.setdefault(p2, []).append((p1, v1, v2))

    regions: list[np.ndarray] = []
    for p1, region_index in enumerate(vor.point_region):
        verts = vor.regions[region_index]
        if verts and all(v >= 0 for v in verts):
            regions.append(np.asarray([vor.vertices[v] for v in verts], dtype=float))
            continue
        finite = {v for v in verts if v >= 0}
        far: list[np.ndarray] = []
        for p2, v1, v2 in ridges.get(p1, []):
            if v2 < 0:
                v1, v2 = v2, v1
            if v1 >= 0:
                continue  # a finite ridge already captured above
            tangent = vor.points[p2] - vor.points[p1]
            tangent /= np.linalg.norm(tangent)
            normal = np.array([-tangent[1], tangent[0]])
            midpoint = vor.points[[p1, p2]].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, normal)) * normal
            far.append(vor.vertices[v2] + direction * radius)
            finite.add(v2)
        poly = np.asarray([vor.vertices[v] for v in finite if v >= 0] + far, dtype=float)
        centroid = poly.mean(axis=0)
        angle = np.arctan2(poly[:, 1] - centroid[1], poly[:, 0] - centroid[0])
        regions.append(poly[np.argsort(angle)])
    return regions


def _polygonal_parts(geom) -> list[Polygon]:
    """Polygonal pieces of a clip result (Polygon, MultiPolygon, or collection)."""
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty and geom.area > 0.0 else []
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        return [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty and g.area > 0.0]
    return []


def voronoi_cells(
    seeds: np.ndarray, domain_polygon: Polygon | MultiPolygon
) -> tuple[list[Polygon], np.ndarray]:
    """Clipped Voronoi cells for ``seeds`` inside ``domain_polygon``.

    Returns the convex cell polygons and the matching cell centers. When the clip
    splits a cell (concave domain), the piece that contains the seed is kept so
    the DISV cell center stays inside its cell; if no piece contains the seed the
    largest piece is kept and its representative point becomes the center. A seed
    whose cell falls entirely outside the domain is dropped.
    """
    seeds = np.asarray(seeds, dtype=float)
    if seeds.ndim != 2 or seeds.shape[1] != 2:
        raise ValueError(f"seeds must have shape (n, 2), got {seeds.shape}")
    vor = Voronoi(seeds)
    radius = float(np.ptp(seeds, axis=0).max()) * 3.0
    cells: list[Polygon] = []
    centers: list[np.ndarray] = []
    for i, region in enumerate(_finite_regions(vor, radius)):
        poly = Polygon(region)
        if not poly.is_valid:
            poly = poly.buffer(0)
        parts = _polygonal_parts(poly.intersection(domain_polygon))
        if not parts:
            continue
        seed = seeds[i]
        chosen = next((part for part in parts if part.covers(Point(seed))), None)
        if chosen is not None:
            center = seed
        else:
            chosen = max(parts, key=lambda g: g.area)
            center = np.asarray(chosen.representative_point().coords[0], dtype=float)
        cells.append(chosen)
        centers.append(center)
    return cells, np.asarray(centers, dtype=float).reshape(-1, 2)


def voronoi_planar_mesh(
    seeds: np.ndarray,
    domain_polygon: Polygon | MultiPolygon,
    *,
    vertex_decimals: int = 3,
) -> HydroMesh:
    """Build a ragged-polygon planar ``HydroMesh`` (Voronoi/PEBI dual).

    Cell centers are stored as ``cell_data["disv_cell_center"]`` (the seeds), so
    the DISV export writes exact perpendicular-bisector cell centers. Coincident
    cell-boundary vertices are merged at ``vertex_decimals`` places (default 1 mm).
    """
    cells, centers = voronoi_cells(seeds, domain_polygon)
    vertex_index: dict[tuple[float, float], int] = {}
    vertices: list[list[float]] = []
    connectivity: list[np.ndarray] = []
    for poly in cells:
        coords = list(poly.exterior.coords)[:-1]  # drop the closing duplicate
        node_ids: list[int] = []
        for x, y in coords:
            key = (round(float(x), vertex_decimals), round(float(y), vertex_decimals))
            idx = vertex_index.get(key)
            if idx is None:
                idx = len(vertices)
                vertex_index[key] = idx
                vertices.append([float(x), float(y)])
            node_ids.append(idx)
        connectivity.append(np.asarray(node_ids, dtype=int))

    return HydroMesh(
        vertices=np.asarray(vertices, dtype=float),
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=tuple(connectivity)),),
        cell_data={"disv_cell_center": np.asarray(centers, dtype=float)},
    )


def voronoi_dual_of_mesh(
    planar_mesh: HydroMesh,
    domain_polygon: Polygon | MultiPolygon,
    *,
    vertex_decimals: int = 3,
) -> HydroMesh:
    """Voronoi dual of a triangular planar mesh, using its vertices as seeds.

    The triangulation's vertices become the Voronoi generators, so the existing
    refinement / constraint conformance (encoded in the vertex placement) is
    preserved and only the dual + clip is applied. ``vertex_decimals`` is the
    coordinate-merge precision (default 1 mm, valid for a projected metric CRS).
    """
    seeds = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    return voronoi_planar_mesh(seeds, domain_polygon, vertex_decimals=vertex_decimals)


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

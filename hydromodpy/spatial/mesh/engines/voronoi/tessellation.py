"""Voronoi cells of the seeds, clipped to the domain, and their shared vertices.

Every function works in the local frame. GEOS builds the cells in seed order
(``voronoi_polygons(ordered=True)``); a cell wholly inside the domain is kept
as is, the others are clipped. A clipped cell split in pieces keeps the piece
that holds its seed. The vertices of the cells are then identified by a 1 mm
integer key, close keys merged, and repeated corners dropped: the topology
comes from shared vertex ids, never from rounded coordinates.

``voronoi_planar_mesh`` gives the Voronoi (PEBI) dual of a set of seeds
clipped to a domain as a ragged-polygon ``HydroMesh``, built in the local
frame of the domain: Qhull and GEOS lose digits on Lambert-93 coordinates, and
two seeds a few metres apart can give two identical cells.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.exceptions import MeshGenerationError
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, local_frame
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import VERTEX_MERGE_M, vertex_keys
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

__all__ = [
    "BOUNDARY_SEED_ROUNDS",
    "MAX_LISTED",
    "ORPHAN_AREA_SHARE",
    "CellTopology",
    "Tessellation",
    "cell_topology",
    "tessellate",
    "voronoi_cells",
    "voronoi_envelope",
    "voronoi_planar_mesh",
]

ORPHAN_AREA_SHARE = 1.0e-12
"""A clipped piece away from its seed counts as an orphan above this share of the domain area."""

BOUNDARY_SEED_ROUNDS = 3
"""Rounds of boundary seeds added for orphan pieces and holed cells."""

_ENVELOPE_SIZES = 10.0
"""The envelope extends at least this many largest cell sizes past the domain."""

MAX_LISTED = 20
"""Faulty cells named in an error message."""

_SEED_GAP_SHARE = 1.0e-9
"""An added boundary seed closer than this share of the domain extent to a seed is dropped."""

_POLYGON = 3


@dataclass(frozen=True, eq=False)
class Tessellation:
    """Clipped cells of the seeds; boundary seeds added for orphans sit at ``n_fixed``.

    ``seeds`` is the input array with the added boundary seeds inserted just
    after the fixed seeds, so the ids of the fixed seeds do not change and
    ``n_fixed`` grows by ``boundary_seeds_added``.
    """

    seeds: np.ndarray
    n_fixed: int
    cells: np.ndarray
    boundary_seeds_added: int


@dataclass(frozen=True, eq=False)
class CellTopology:
    """Shared vertices ``(m, 2)`` and one ring of vertex ids per cell, in seed order."""

    vertices: np.ndarray
    rings: tuple[np.ndarray, ...]


def voronoi_envelope(domain: BaseGeometry, h_max: float) -> BaseGeometry:
    """Box around the domain, larger than it by ``max(extent, 10 h_max)`` on each side."""
    xmin, ymin, xmax, ymax = domain.bounds
    margin = max(xmax - xmin, ymax - ymin, _ENVELOPE_SIZES * float(h_max))
    return shapely.box(xmin - margin, ymin - margin, xmax + margin, ymax + margin)


def voronoi_cells(seeds: np.ndarray, domain: BaseGeometry, envelope: BaseGeometry) -> np.ndarray:
    """One clipped polygon per seed ``(n, 2)``, in seed order, all in the local frame.

    Raises ``MeshGenerationError`` when two seeds coincide or when a seed has
    no cell inside the domain.
    """
    cells, _ = _clipped(np.asarray(seeds, dtype=np.float64), domain, envelope)
    return cells


def tessellate(
    seeds: np.ndarray,
    n_fixed: int,
    domain: BaseGeometry,
    envelope: BaseGeometry,
    *,
    rounds: int = BOUNDARY_SEED_ROUNDS,
) -> Tessellation:
    """Clip the cells; give each orphan piece and each hole inside one cell a boundary seed.

    An orphan is a piece of a clipped cell away from its seed, larger than
    :data:`ORPHAN_AREA_SHARE` of the domain area (a concave or staircase
    domain). Its boundary seed goes to the point of the domain boundary nearest
    its centroid. A cell that wraps a hole of the domain gets a seed on the
    hole ring, at the point farthest from its own seed. After *rounds* rounds
    what is left is caught by the area gate. A hole that touches another ring
    at a point leaves a sliver at that point whatever the seed: the gate stops it.
    """
    points = np.asarray(seeds, dtype=np.float64)
    fixed = int(n_fixed)
    shapely.prepare(domain)
    boundary = domain.boundary
    min_gap = _SEED_GAP_SHARE * max(_extent(domain), 1.0)
    added = 0
    cells, orphans = _clipped(points, domain, envelope)
    for _ in range(rounds):
        candidates = np.vstack([_orphan_seeds(orphans, boundary), _hole_seeds(cells, points)])
        candidates = _far_from(candidates, points, min_gap)
        if not len(candidates):
            break
        points = np.vstack([points[:fixed], candidates, points[fixed:]])
        fixed += len(candidates)
        added += len(candidates)
        cells, orphans = _clipped(points, domain, envelope)
    return Tessellation(seeds=points, n_fixed=fixed, cells=cells, boundary_seeds_added=added)


def cell_topology(cells: np.ndarray, frame: LocalFrame) -> CellTopology:
    """Shared vertices and rings of the exterior rings of *cells*, all in the local frame.

    Vertices are keyed by ``round(x / 1 mm) * 2^32 + round(y / 1 mm)``; distinct
    keys closer than 1 mm are merged too. Each vertex keeps the float
    coordinates of its first occurrence in seed order. Consecutive repeated
    corners of a ring are dropped (the near-zero edges where four cells meet).
    Raises ``MeshGenerationError`` when a ring keeps fewer than three corners.
    """
    rings = shapely.get_exterior_ring(np.asarray(cells))
    coords, owner = shapely.get_coordinates(rings, return_index=True)
    closing = np.r_[owner[1:] != owner[:-1], True]
    coords, owner = coords[~closing], owner[~closing]
    vertex_of = _merged_vertices(coords)
    keep = _new_corner(vertex_of, owner)
    coords, vertex_of, owner = coords[keep], vertex_of[keep], owner[keep]
    counts = np.bincount(owner, minlength=len(cells))
    short = np.flatnonzero(counts < 3)
    if short.size:
        seeds = [shapely.get_coordinates(cells[i])[0] for i in short[:MAX_LISTED]]
        world = frame.to_world(np.asarray(seeds).reshape(-1, 2))
        listed = "; ".join(
            f"cell {int(i)} near ({x:.3f}, {y:.3f})"
            for i, (x, y) in zip(short[:MAX_LISTED], world, strict=True)
        )
        raise MeshGenerationError(
            f"gate G5: {short.size} cells keep fewer than 3 corners after the 1 mm vertex "
            f"merge: {listed}"
        )
    _, compact = np.unique(vertex_of, return_inverse=True)
    first = np.full(int(compact.max()) + 1, len(coords), dtype=np.int64)
    np.minimum.at(first, compact, np.arange(len(compact)))
    vertices = coords[first]
    return CellTopology(
        vertices=vertices,
        rings=tuple(np.split(compact.astype(np.int64), np.cumsum(counts)[:-1])),
    )


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


def _extent(domain: BaseGeometry) -> float:
    """Largest side of the domain bounding box [m]."""
    xmin, ymin, xmax, ymax = domain.bounds
    return max(xmax - xmin, ymax - ymin)


def _clipped(
    seeds: np.ndarray, domain: BaseGeometry, envelope: BaseGeometry
) -> tuple[np.ndarray, np.ndarray]:
    """The clipped cell of each seed, and the orphan pieces left by the clip."""
    try:
        collection = shapely.voronoi_polygons(
            shapely.multipoints(seeds), extend_to=envelope, ordered=True
        )
    except GEOSException as error:
        raise MeshGenerationError(f"GEOS Voronoi failed, two seeds coincide: {error}") from error
    cells = np.asarray(shapely.get_parts(collection))
    if len(cells) != len(seeds):
        raise MeshGenerationError(
            f"GEOS returned {len(cells)} Voronoi cells for {len(seeds)} seeds: two seeds coincide"
        )
    shapely.prepare(domain)
    cut = np.flatnonzero(~shapely.contains_properly(domain, cells))
    orphans = np.empty(0, dtype=object)
    if cut.size:
        clipped = shapely.intersection(cells[cut], domain)
        single = shapely.get_type_id(clipped) == _POLYGON
        cells[cut[single]] = clipped[single]
        split = np.flatnonzero(~single)
        if split.size:
            kept, orphans = _seed_pieces(clipped[split], seeds[cut[split]], cut[split])
            cells[cut[split]] = kept
            orphans = orphans[shapely.area(orphans) > ORPHAN_AREA_SHARE * domain.area]
    return cells, orphans


def _seed_pieces(
    clipped: np.ndarray, seeds: np.ndarray, ids: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The piece of each multi-part clip nearest its seed, and the other polygonal pieces."""
    parts, owner = shapely.get_parts(clipped, return_index=True)
    polygonal = (shapely.get_type_id(parts) == _POLYGON) & (shapely.area(parts) > 0.0)
    parts, owner = parts[polygonal], owner[polygonal]
    missing = np.setdiff1d(np.arange(len(clipped)), owner)
    if missing.size:
        raise MeshGenerationError(
            "gate G0: no part of the cell of seed(s) "
            f"{ids[missing][:MAX_LISTED].tolist()} lies inside the domain"
        )
    distance = shapely.distance(parts, shapely.points(seeds[owner]))
    order = np.lexsort((distance, owner))
    first = order[np.r_[True, owner[order][1:] != owner[order][:-1]]]
    is_kept = np.zeros(len(parts), dtype=bool)
    is_kept[first] = True
    return parts[first], parts[~is_kept]


def _orphan_seeds(orphans: np.ndarray, boundary: BaseGeometry) -> np.ndarray:
    """Boundary points nearest the centroids of the orphan pieces, ``(k, 2)``."""
    if not len(orphans):
        return np.empty((0, 2))
    lines = shapely.shortest_line(boundary, shapely.centroid(orphans))
    return shapely.get_coordinates(shapely.get_point(lines, 0))


def _hole_seeds(cells: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """A point of each hole ring that a cell wraps, the farthest from the cell seed."""
    holed = np.flatnonzero(shapely.get_num_interior_rings(cells) > 0)
    if not holed.size:
        return np.empty((0, 2))
    rings, owner = shapely.get_rings(cells[holed], return_index=True)
    interior = np.r_[False, owner[1:] == owner[:-1]]
    coords, ring_of = shapely.get_coordinates(rings[interior], return_index=True)
    cell_of = holed[owner[interior][ring_of]]
    distance = np.hypot(*(coords - seeds[cell_of]).T)
    order = np.lexsort((-distance, ring_of))
    first = order[np.r_[True, ring_of[order][1:] != ring_of[order][:-1]]]
    return coords[first]


def _far_from(candidates: np.ndarray, seeds: np.ndarray, gap: float) -> np.ndarray:
    """The distinct candidates farther than *gap* from every seed and from each other."""
    if not len(candidates):
        return candidates
    candidates = candidates[np.sort(np.unique(candidates, axis=0, return_index=True)[1])]
    distance, _ = cKDTree(seeds).query(candidates, k=1)
    candidates = candidates[distance > gap]
    if len(candidates) > 1:
        close = cKDTree(candidates).query_pairs(gap, output_type="ndarray")
        candidates = np.delete(candidates, np.unique(close.max(axis=1)), axis=0)
    return candidates


def _merged_vertices(coords: np.ndarray) -> np.ndarray:
    """Vertex id of each corner: 1 mm key, then keys closer than 1 mm merged.

    Ids are numbered in order of first occurrence, the smallest id of a merged
    group being its representative.
    """
    key = vertex_keys(coords)
    _, first, inverse = np.unique(key, return_index=True, return_inverse=True)
    rank = np.empty(len(first), dtype=np.int64)
    rank[np.argsort(first, kind="stable")] = np.arange(len(first))
    unique_xy = coords[np.sort(first)]
    vertex_of = rank[inverse.ravel()]
    pairs = cKDTree(unique_xy).query_pairs(VERTEX_MERGE_M, output_type="ndarray")
    if not len(pairs):
        return vertex_of
    n = len(unique_xy)
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    _, label = connected_components(graph, directed=False)
    representative = np.full(label.max() + 1, n, dtype=np.int64)
    np.minimum.at(representative, label, np.arange(n))
    return representative[label][vertex_of]


def _new_corner(vertex_of: np.ndarray, owner: np.ndarray) -> np.ndarray:
    """Mask of the corners that differ from the previous corner of their ring, cyclically."""
    same_ring = np.r_[False, owner[1:] == owner[:-1]]
    keep = ~(same_ring & (vertex_of == np.r_[-1, vertex_of[:-1]]))
    starts = np.flatnonzero(~same_ring)
    ends = np.r_[starts[1:], len(owner)] - 1
    # After the run removal the last kept corner of a ring may repeat its first one.
    last_kept = _last_kept(keep, starts, ends)
    repeat = (last_kept != starts) & (vertex_of[last_kept] == vertex_of[starts])
    keep[last_kept[repeat]] = False
    return keep


def _last_kept(keep: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Index of the last kept corner of each ring ``[start, end]``."""
    position = np.where(keep, np.arange(len(keep)), -1)
    running = np.maximum.accumulate(position)
    return running[ends]

"""Cell / idomain / bed geometry helpers for the MF6 LAK builder.

Geometry primitives (interior faces of a cell, perpendicular distance, first
active layer below a lake column), lake-footprint resolution (interior-ring drop,
enclosed-cell fill, shared-cell arbitration) and the cells behind a cutoff wall.
Private to the ``builders`` package; the public ``lake`` facade imports the ones
its builder functions call.

It also holds the cells a lake polygon owns and the faces of a cutoff wall laid
on the shore, which the HFB builder (``flow_barrier.py``) reads too. A mesh whose
faces follow a closed family line (a lake shore on triangles) splits into
regions once the faces of that family are cut: a polygon then owns the regions
it covers, cell for cell, with no sliver of a cell outside it. A mesh whose
faces only approach the line (a regular grid, the Voronoi dual of a
triangulation) has no such regions; the cells a polygon overlaps by a positive
area are the cells it reaches there.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.strtree import STRtree

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders._lake_definitions import _active_lake_definitions
from hydromodpy.spatial.mesh.model.derived_geometry import cell_polygons
from hydromodpy.spatial.mesh.ops.flow_barrier import BarrierFace, barrier_edges

if TYPE_CHECKING:
    from shapely.geometry import LineString
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

logger = get_logger(__name__)


def _abacus_volume(abacus: object) -> list[float] | None:
    """Return the ``volume`` column from a loaded abacus payload, if present."""
    if abacus is None:
        return None
    volume = (
        abacus.get("volume") if isinstance(abacus, Mapping) else getattr(abacus, "volume", None)
    )
    if volume is None:
        return None
    return [float(v) for v in volume]


def _abacus_stage_sarea(abacus: object) -> tuple[list[float] | None, list[float] | None]:
    """Return the ``(stage, sarea)`` columns from a loaded abacus payload."""
    if abacus is None:
        return None, None
    if isinstance(abacus, Mapping):
        stage = abacus.get("stage")
        sarea = abacus.get("sarea")
    else:
        stage = getattr(abacus, "stage", None)
        sarea = getattr(abacus, "sarea", None)
    if stage is None or sarea is None:
        return None, None
    return [float(v) for v in stage], [float(v) for v in sarea]


def _cell_faces(cell_mesh: PlanarCellMesh, cell: int) -> list[tuple[int, int, int, float]]:
    """Return the interior faces of one cell, in the order of its vertices.

    Each face is ``(neighbour, node_a, node_b, length)`` with ``node_a < node_b``;
    a corner repeated in the cell gives no face, and a boundary side has no
    neighbour and is left out.
    """
    geometry = cell_mesh.geometry
    row = geometry.padded_connectivity[cell]
    nodes = row[row >= 0].astype(np.int64)
    following = np.roll(nodes, -1)
    keep = nodes != following
    node_a = np.minimum(nodes, following)[keep]
    node_b = np.maximum(nodes, following)[keep]
    edges = geometry.edge_ids(node_a, node_b)
    pairs = geometry.edge_cells[edges]
    neighbours = np.where(pairs[:, 0] == cell, pairs[:, 1], pairs[:, 0])
    return [
        (int(neighbour), int(a), int(b), float(length))
        for neighbour, a, b, length in zip(
            neighbours, node_a, node_b, geometry.edge_length[edges], strict=True
        )
        if neighbour >= 0
    ]


def _point_to_segment_distance(point: np.ndarray, seg_a: np.ndarray, seg_b: np.ndarray) -> float:
    """Return the perpendicular distance from a point to a segment's line.

    For a Voronoi mesh the neighbour centroid projects onto the shared edge, so
    this is the exact half cell-to-cell distance (CVFD ``connlen``). For other
    meshes it is the best local estimate.
    """
    ab = seg_b - seg_a
    length_sq = float(ab[0] ** 2 + ab[1] ** 2)
    if length_sq == 0.0:
        return float(np.hypot(point[0] - seg_a[0], point[1] - seg_a[1]))
    # Signed area / base length = perpendicular distance to the supporting line.
    ap = point - seg_a
    cross = float(ab[0] * ap[1] - ab[1] * ap[0])
    return abs(cross) / float(np.sqrt(length_sq))


def _first_active_layer_below(
    idomain: np.ndarray, cell_id: int, occupied_layers: int, nlay: int
) -> int | None:
    """Return the first active layer below the lake's occupied layers, or None."""
    for lay in range(occupied_layers, nlay):
        if int(idomain[lay, cell_id]) > 0:
            return lay
    return None


def _lake_bed_layers(idomain_col: np.ndarray, occupied_layers: int) -> np.ndarray:
    """Return the layers a carved bed re-grades in one lake column.

    The cap layers are all kept, pass-through cells included, because the lake
    takes them. Below the cap a pass-through cell (``idomain = -1``) is left out:
    it stays flat and the active cell next to it keeps the thickness.
    """
    column = np.asarray(idomain_col)
    layers = np.arange(column.size)
    return layers[(layers < occupied_layers) | (column != -1)]


def _flat_pass_through(
    top: float, layers: np.ndarray, bottoms: np.ndarray, nlay: int
) -> np.ndarray:
    """Return the bottoms of a column whose left-out layers sit flat on the cell above.

    ``bottoms`` holds the new bottom of each layer of ``layers``. A layer not in
    ``layers`` gets the bottom of the cell above it, so it has no thickness, as the
    pinch-out leaves a pass-through cell.
    """
    out = np.empty(nlay, dtype=float)
    upper = float(top)
    kept = dict(zip((int(k) for k in layers), (float(b) for b in bottoms), strict=True))
    for lay in range(nlay):
        upper = kept.get(lay, upper)
        out[lay] = upper
    return out


def _drop_interior_rings(geometry: object) -> object:
    """Return the geometry with its interior rings (islands) removed.

    Used when a lake sets ``fill_enclosed_cells``: cells enclosed by the lake
    footprint (inside an island ring, or a sub-cell classification pocket) are
    then claimed by the lake and the footprint stays contiguous. A geometry
    without interior rings is returned unchanged.
    """
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geometry, Polygon):
        return Polygon(geometry.exterior) if geometry.interiors else geometry
    if isinstance(geometry, MultiPolygon):
        return MultiPolygon([Polygon(part.exterior) for part in geometry.geoms])
    return geometry


def _fill_lake_enclosed_cells(
    cells_by_lake: dict[str, list[int]],
    intersected_area_by_lake: dict[str, dict[int, float]],
    solver_mesh: SolverMesh,
) -> None:
    """Absorb every interior cell whose faces all touch lake cells into that lake.

    A cell entirely surrounded by lake cells is a pinhole in the intersected footprint
    (the polygon just missed it) and would otherwise stay a lone active column inside the
    reservoir. Only interior cells qualify: a cell on the mesh boundary has an open edge
    (fewer face-neighbours than polygon edges), so its water can still leave and it is not
    lake-enclosed. Assign each hole to the lake owning most of its neighbours, with the full
    cell area. Iterated so a hole freed by a previous fill can itself be closed.
    """
    from collections import Counter

    n_cells = int(solver_mesh.n_cells)
    adjacency = solver_mesh.face_adjacency()
    active0 = solver_mesh.top_active_layer() >= 0
    areas = solver_mesh.cell_areas()
    n_edges = (solver_mesh.cell_mesh.geometry.padded_connectivity >= 0).sum(axis=1).tolist()

    lake_of: dict[int, str] = {}
    for lake_id, cells in cells_by_lake.items():
        for cell in cells:
            lake_of[int(cell)] = lake_id

    filled = 0
    for _ in range(n_cells):
        added = False
        for cell in range(n_cells):
            if cell in lake_of or not active0[cell]:
                continue
            neighbours = adjacency[cell]
            # Interior only: an open (unshared) polygon edge means fewer neighbours than
            # edges, so a boundary cell is never treated as lake-enclosed.
            if n_edges[cell] < 3 or len(neighbours) != n_edges[cell]:
                continue
            if any(nb not in lake_of for nb in neighbours):
                continue
            counts = Counter(lake_of[nb] for nb in neighbours)
            owner = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            cells_by_lake[owner].append(cell)
            intersected_area_by_lake[owner][cell] = float(areas[cell])
            lake_of[cell] = owner
            filled += 1
            added = True
        if not added:
            break
    if filled:
        logger.info("Lake footprint: absorbed %d fully lake-enclosed cell(s).", filled)


def _drop_cutoff_wall_downstream_cells(
    model,
    cells_by_lake: dict[str, list[int]],
    intersected_area_by_lake: dict[str, dict[int, float]],
    solver_mesh: SolverMesh,
) -> None:
    """Drop lake cells on the downstream side of the cutoff wall laid on the shore.

    The wall runs with the lake on its left (``cutoff_wall_line``), so a cell
    whose centre lies on its right is behind the dam. The side is read at the
    nearest point of the wall, so a curved wall is followed. On an engine whose
    faces follow the shore the cut footprint leaves no such cell; on the regular
    grid the overlap cells straddling the dam shore go. Dropping them makes the
    footprint stop at the dam, so idomain, the bed carve, RCH/EVT masking, SFR
    movers and the LAK package see a footprint that does not leak past the wall.
    """
    definitions = _active_lake_definitions(model)
    centres = np.asarray(solver_mesh.cell_mesh.centers, dtype=float)
    for lake_id, cells in list(cells_by_lake.items()):
        line = definitions.get(lake_id, {}).get("cutoff_wall_line")
        if line is None or getattr(line, "is_empty", True) or not cells:
            continue
        ids = np.asarray(cells, dtype=np.int64)
        behind = downstream_of_wall(line, centres[ids])
        if behind.all():
            raise ValueError(
                f"cutoff wall for lake '{lake_id}' classifies every cell as downstream "
                "of the voile; check the trace orientation and position."
            )
        if not behind.any():
            continue
        cells_by_lake[lake_id] = [int(c) for c in ids[~behind]]
        area = intersected_area_by_lake.get(lake_id)
        if isinstance(area, dict):
            for c in ids[behind]:
                area.pop(int(c), None)
        logger.warning(
            "Cutoff wall '%s': dropped %d LAK cell(s) downstream of the voile "
            "(implicit perfect seal, independent of the HFB hydchr).",
            lake_id,
            int(behind.sum()),
        )


def _resolve_shared_lake_cells(
    cells_by_lake: dict[str, list[int]],
    intersected_area_by_lake: Mapping[str, Mapping[int, float]],
) -> None:
    """Assign each cell claimed by >1 lake to its largest-overlap lake, in place.

    MF6 LAK allows one vertical lake connection per GWF cell, so two lakes sharing
    a cell would deactivate it twice and emit two VERTICAL connections into the
    same aquifer cell below. Adjacent lakes (a pre-retenue and its reservoir across
    a narrow sill) can each clip the same edge cell when the mesh is coarser than
    the gap. Rather than reject the model, the cell goes to the lake it overlaps
    most (by intersected area) and is dropped from the others, so the footprints
    stay cell-disjoint. Logged, never silent. A lake left with zero cells is a real
    geometry error (fully swallowed by a neighbour) and still raises.
    """
    owners: dict[int, list[str]] = {}
    for lake_id, cells in cells_by_lake.items():
        for cell in cells:
            owners.setdefault(int(cell), []).append(str(lake_id))
    shared = {cell: lakes for cell, lakes in owners.items() if len(lakes) > 1}
    if not shared:
        return
    for cell, lake_ids in shared.items():
        winner = max(
            lake_ids,
            key=lambda lid, c=cell: float(intersected_area_by_lake.get(lid, {}).get(c, 0.0)),
        )
        for lid in lake_ids:
            if lid != winner:
                cells_by_lake[lid] = [c for c in cells_by_lake[lid] if int(c) != cell]
    emptied = [lid for lid, cells in cells_by_lake.items() if not cells]
    if emptied:
        raise ValueError(
            f"flow.sinks_sources.lakes: {sorted(emptied)} lost every grid cell to an "
            "overlapping neighbour after sharing resolution; the footprints overlap too much. "
            "Separate the lake polygons or refine the mesh across the sill."
        )
    logger.warning(
        "flow.sinks_sources.lakes: %d cell(s) claimed by multiple lakes reassigned to their "
        "largest-overlap lake (sill cells on a mesh coarser than the lake gap). Refine "
        "mesh.lake_refinement further if the sill needs to be sharper.",
        len(shared),
    )


# -- Cells of a lake polygon -------------------------------------------------

_INTERIOR_SHARE = 0.5
"""A region belongs to the polygon that covers more than this share of its area."""

_MIN_OVERLAP_SHARE = 1e-6
"""An overlap below this share of the cell area is a sliver, not a reach."""


def polygon_overlap(
    cell_mesh: PlanarCellMesh, polygon: BaseGeometry
) -> tuple[np.ndarray, np.ndarray]:
    """Return the sorted ids of the cells ``polygon`` overlaps, and the overlap areas.

    A cell that only touches the polygon along an edge or at a point has no
    positive overlap and is left out. A sliver smaller than
    ``_MIN_OVERLAP_SHARE`` of the cell area is left out too: it is a rounding
    artefact of the outline, not a reach.
    """
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.geometry.padded_connectivity)
    candidates = np.sort(STRtree(polygons).query(polygon, predicate="intersects"))
    areas = shapely.area(shapely.intersection(polygons[candidates], polygon))
    cell_areas = np.asarray(cell_mesh.geometry.areas, dtype=float)[candidates]
    keep = areas > _MIN_OVERLAP_SHARE * cell_areas
    return candidates[keep].astype(np.int64), np.asarray(areas[keep], dtype=float)


def family_regions(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    """Return the region label of every cell once the faces of ``family`` are cut."""
    geometry = cell_mesh.geometry
    n_cells = cell_mesh.n_cells
    cut = np.zeros(geometry.edge_nodes.shape[0], dtype=bool)
    rows = cell_mesh.face_rows(family)
    if rows.any():
        table = cell_mesh.face_families
        edges = geometry.edge_ids(table.node_a[rows], table.node_b[rows])
        cut[edges[edges >= 0]] = True
    joined = (geometry.edge_cells[:, 1] >= 0) & ~cut
    first, second = geometry.edge_cells[joined, 0], geometry.edge_cells[joined, 1]
    graph = coo_matrix(
        (np.ones(first.size, dtype=np.int8), (first, second)), shape=(n_cells, n_cells)
    )
    _, labels = connected_components(graph, directed=False)
    return labels.astype(np.int64)


def interior_cells(cell_mesh: PlanarCellMesh, family: str, polygon: BaseGeometry) -> np.ndarray:
    """Return the sorted cells of the ``family`` regions ``polygon`` covers for most of their area.

    Each region bounded by the faces of ``family`` is owned by the polygon that
    covers more than half of it, so a cell is inside or outside as a whole. A
    cell of a region the polygon does not own is still its own when the polygon
    covers more than half of that cell: a mesh that follows the shore smoothed
    at its cell size leaves the arms narrower than a cell out of the regions,
    and those cells come back one by one. An empty result means no region of
    the family lies inside the polygon: the mesh faces were not built on its
    outline.
    """
    labels = family_regions(cell_mesh, family)
    n_regions = int(labels.max(initial=-1)) + 1
    cells, overlap = polygon_overlap(cell_mesh, polygon)
    covered = np.bincount(labels[cells], weights=overlap, minlength=n_regions)
    region_area = np.bincount(labels, weights=cell_mesh.geometry.areas, minlength=n_regions)
    inside = covered > _INTERIOR_SHARE * region_area
    if not inside.any():
        return np.empty(0, dtype=np.int64)
    owned = inside[labels]
    areas = np.asarray(cell_mesh.geometry.areas, dtype=float)
    owned[cells[overlap > _INTERIOR_SHARE * areas[cells]]] = True
    return np.flatnonzero(owned).astype(np.int64)


# -- Faces of a cutoff wall laid on the shore --------------------------------


def downstream_of_wall(line: LineString, points: np.ndarray) -> np.ndarray:
    """Whether each point lies across a wall that has the lake on its left.

    The side is read at the nearest point of the wall, against the local
    direction of the wall there, so a curved wall is followed. A point whose
    nearest point of the wall is one of its ends lies round the wall, not
    across it, and a point on the wall is on neither side: neither is downstream.
    """
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    along = shapely.line_locate_point(line, shapely.points(points))
    step = 1.0e-6 * max(line.length, 1.0)
    before = shapely.get_coordinates(
        shapely.line_interpolate_point(line, np.maximum(along - step, 0.0))
    )
    after = shapely.get_coordinates(
        shapely.line_interpolate_point(line, np.minimum(along + step, line.length))
    )
    foot = shapely.get_coordinates(shapely.line_interpolate_point(line, along))
    tangent = after - before
    offset = points - foot
    across = tangent[:, 0] * offset[:, 1] - tangent[:, 1] * offset[:, 0] < 0.0
    tip = 1.0e-9 * max(line.length, 1.0)
    return across & (along > tip) & (along < line.length - tip)


def lake_shore_faces(
    cell_mesh: PlanarCellMesh, line: LineString, lake_cells: np.ndarray
) -> np.ndarray:
    """Interior edges between a lake cell and a cell downstream of the wall.

    *line* is a wall with the lake on its left. Every face of the lake cell set
    whose outer cell lies downstream of the wall belongs to the wall: barring
    them all leaves no cell between the reservoir and the wall.
    """
    geometry = cell_mesh.geometry
    lake = np.zeros(geometry.n_cells, dtype=bool)
    lake[np.asarray(lake_cells, dtype=np.int64)] = True
    pairs = geometry.edge_cells
    interior = pairs[:, 1] >= 0
    first_in = lake[pairs[:, 0]]
    second_in = np.where(interior, lake[np.maximum(pairs[:, 1], 0)], False)
    shore = np.flatnonzero(interior & (first_in != second_in))
    outer = np.where(first_in[shore], pairs[shore, 1], pairs[shore, 0])
    return shore[downstream_of_wall(line, cell_mesh.centers[outer])]


def cutoff_wall_faces(
    cell_mesh: PlanarCellMesh,
    line: LineString,
    lake_cells: np.ndarray,
    trace: LineString | None = None,
) -> list[BarrierFace]:
    """The faces of a lake cutoff wall: its shore faces and the faces of its line.

    *line* is the wall laid on the shore, lake on its left. Along the shore the
    wall is every face between a lake cell and a cell downstream of it, so it
    hugs the lake cell set; on a regular grid that is the staircase around the
    overlap cells. The faces of the line (:func:`barrier_edges`) are barred
    too: on an engine that follows the barrier family, the faces on the wall,
    wings included; on a staircase, the faces the line crosses, which carry
    the wings and close the fence where the cells round a corner of the shore.
    A face between two lake cells is never barred. ``s`` is the position along
    *trace* (the declared trace, whose vertices carry the depths), *line* when
    none is given.
    """
    geometry = cell_mesh.geometry
    lake = np.zeros(geometry.n_cells, dtype=bool)
    lake[np.asarray(lake_cells, dtype=np.int64)] = True
    rows = np.union1d(lake_shore_faces(cell_mesh, line, lake_cells), barrier_edges(cell_mesh, line))
    pairs = geometry.edge_cells[rows]
    rows = rows[~(lake[pairs[:, 0]] & lake[pairs[:, 1]])]
    if not rows.size:
        return []
    station_line = line if trace is None else trace
    total = float(station_line.length) or 1.0
    along = shapely.line_locate_point(station_line, shapely.points(geometry.edge_midpoint[rows]))
    stations = along / total
    cells = geometry.edge_cells[rows]
    return [
        BarrierFace(
            cell_a=int(cells[k, 0]),
            cell_b=int(cells[k, 1]),
            s=float(stations[k]),
            length=float(geometry.edge_length[rows[k]]),
        )
        for k in np.argsort(stations, kind="stable")
    ]


def wall_leaks(
    cell_mesh: PlanarCellMesh,
    line: LineString,
    lake_cells: np.ndarray,
    barred: list[BarrierFace],
    *,
    reach: float,
) -> np.ndarray:
    """Lake-side cells the downstream side reaches without crossing a barred face.

    The walk starts from every non-lake cell downstream of *line* (lake on its
    left) within *reach* [m] of it, and moves through the faces left open
    between cells within that reach. A cell whose nearest point of the wall is
    an end of the wall is outside the walk, so the walk never goes round a
    wing. A closed wall returns no cell.
    """
    geometry = cell_mesh.geometry
    n_cells = geometry.n_cells
    centres = shapely.points(cell_mesh.centers)
    along = shapely.line_locate_point(line, centres)
    tip = 1.0e-9 * max(line.length, 1.0)
    walk = (shapely.distance(centres, line) <= reach) & (along > tip) & (along < line.length - tip)
    lake = np.zeros(n_cells, dtype=bool)
    lake[np.asarray(lake_cells, dtype=np.int64)] = True
    downstream = downstream_of_wall(line, cell_mesh.centers) & ~lake
    pairs = geometry.edge_cells[geometry.edge_cells[:, 1] >= 0]
    keys = pairs[:, 0] * n_cells + pairs[:, 1]
    closed = np.array([face.cell_a * n_cells + face.cell_b for face in barred], dtype=np.int64)
    open_pairs = pairs[~np.isin(keys, closed) & walk[pairs[:, 0]] & walk[pairs[:, 1]]]
    graph = coo_matrix(
        (np.ones(len(open_pairs)), (open_pairs[:, 0], open_pairs[:, 1])), shape=(n_cells, n_cells)
    )
    component = connected_components(graph, directed=False)[1]
    reached = np.isin(component, component[walk & downstream])
    return np.flatnonzero(reached & walk & ~downstream)

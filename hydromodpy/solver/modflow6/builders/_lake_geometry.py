"""Cell / idomain / bed geometry helpers for the MF6 LAK builder.

Geometry primitives (interior faces of a cell, perpendicular distance, first
active layer below a lake column), lake-footprint resolution (interior-ring drop,
enclosed-cell fill, shared-cell arbitration) and the cells behind a cutoff wall.
Private to the ``builders`` package; the public ``lake`` facade imports the ones
its builder functions call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders._lake_definitions import _active_lake_definitions
from hydromodpy.spatial.mesh.ops.flow_barrier import downstream_of_wall

if TYPE_CHECKING:
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
    n_nodes = np.int64(cell_mesh.mesh.n_nodes)
    edge_keys = geometry.edge_nodes[:, 0] * n_nodes + geometry.edge_nodes[:, 1]
    edges = np.searchsorted(edge_keys, node_a * n_nodes + node_b)
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

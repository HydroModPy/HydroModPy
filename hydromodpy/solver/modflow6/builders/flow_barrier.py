"""Build the MODFLOW 6 HFB (Horizontal Flow Barrier) stress-period data.

Turns the faces of a barrier line (``spatial.mesh.cells.barrier_faces``: the barrier
family faces laid on it, or the faces it crosses on a staircase) into HFB
rows ``[(lay, cell_a), (lay, cell_b), hydchr]``, one per layer the barrier spans
from the model top down to a (possibly per-segment) depth. ``hydchr`` is the
barrier hydraulic characteristic = ``K_barrier / thickness`` [1/T]; a small value
is a near-impermeable wall (a dam cutoff wall / grout curtain).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.geometry import LineString, Point

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders._lake_definitions import _active_lake_definitions
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    cutoff_wall_faces,
    downstream_of_wall,
    lake_shore_faces,
    wall_leaks,
)
from hydromodpy.solver.modflow6.builders.solver_options import xt3d_is_enabled
from hydromodpy.spatial.mesh.cells.barrier_faces import BarrierFace, barrier_faces_from_line
from hydromodpy.spatial.mesh.model.geometry import cell_polygons

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

logger = get_logger(__name__)


def mesh_footprint(cell_mesh: PlanarCellMesh) -> shapely.Geometry:
    """Return the union of the cell polygons (the planar model domain)."""
    return shapely.union_all(cell_polygons(cell_mesh.mesh.vertices, cell_mesh.connectivity_rows))


def trace_end_gaps(footprint: shapely.Geometry, line: LineString) -> tuple[float, float]:
    """Return the open length [m] left at the start and at the end of a trace.

    The open length is the distance from the trace end to the domain outline,
    when that end lies inside the domain. Flow can go around the barrier
    through this gap. An end on or outside the outline leaves no gap.
    """
    coords = shapely.get_coordinates(line)
    outline = footprint.boundary
    gaps = []
    for xy in (coords[0], coords[-1]):
        point = shapely.Point(float(xy[0]), float(xy[1]))
        inside = footprint.contains(point)
        gaps.append(float(outline.distance(point)) if inside else 0.0)
    return gaps[0], gaps[1]


def _vertex_stations(line: LineString) -> np.ndarray:
    """Normalized cumulative arc-length station [0, 1] of each line vertex."""
    coords = np.asarray(line.coords, dtype=float)[:, :2]
    seg = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1]) or 1.0
    return cum / total


def _interp_depth(s: float, depths: list[float], stations: np.ndarray) -> float:
    """Depth at normalized line position ``s`` from per-vertex ``depths``.

    Anchors each depth at the vertex' real arc-length station, so a digitized dam
    axis with unevenly spaced vertices keeps the depths at the vertices.
    """
    if len(depths) == 1:
        return float(depths[0])
    return float(np.interp(max(0.0, min(1.0, s)), stations, depths))


def _nearest_active_layer_to_band(
    ca: int,
    cb: int,
    barrier_bottom: float,
    top: np.ndarray,
    inactive: np.ndarray,
    nlay: int,
) -> int | None:
    """The layer active at both cells nearest the barrier band, or ``None``.

    When the band foot sits above the aquifer top, seal from the top layer down;
    otherwise the band lies below the aquifer, so seal from the bottom layer up.
    """
    order = range(nlay) if barrier_bottom >= float(top[ca]) else range(nlay - 1, -1, -1)
    for lay in order:
        if not inactive[lay, ca] and not inactive[lay, cb]:
            return int(lay)
    return None


def _layer_interval(lay: int, cell: int, top: np.ndarray, botm: np.ndarray) -> tuple[float, float]:
    """Return (bottom, top) of one layer at one cell."""
    layer_top = float(top[cell]) if lay == 0 else float(botm[lay - 1, cell])
    return float(botm[lay, cell]), layer_top


def _trace_weight(faces: list, trace_length: float) -> tuple[float, float]:
    """Return (chain length, face weight) so the faces sum to the trace length.

    A chain of faces zigzags around the trace and is longer than it. Each face
    hydchr is multiplied by L_trace / sum(L_faces), so the total barrier
    conductance matches the declared wall. The weight never exceeds 1.
    """
    chain = float(sum(f.length for f in faces))
    if chain <= 0.0 or trace_length <= 0.0:
        return chain, 1.0
    weight = trace_length / chain
    if weight >= 1.0 - 1e-9:
        return chain, 1.0
    return chain, weight


def _barrier_band(
    face: BarrierFace,
    top: np.ndarray,
    depths: list[float] | None,
    stations: np.ndarray,
    crest_elevation: float | None,
    base_elevation: float | None,
) -> tuple[float, float]:
    """Top and foot elevations of the barrier at one face."""
    if crest_elevation is None:
        barrier_top = max(float(top[face.cell_a]), float(top[face.cell_b]))
    else:
        barrier_top = float(crest_elevation)
    if base_elevation is not None:
        return barrier_top, float(base_elevation)
    return barrier_top, barrier_top - _interp_depth(face.s, depths, stations)


def _face_layers(
    face: BarrierFace,
    band: tuple[float, float],
    top: np.ndarray,
    botm: np.ndarray,
    inactive: np.ndarray,
    nlay: int,
) -> tuple[list[int], int, bool]:
    """Layers barred at one face, rows dropped over an inactive cell, band clamped.

    A layer is barred when its interval cuts the band at either cell and both
    cells are active there. When the band misses the aquifer entirely at this
    face (an absolute band over a terrain-following bottom), the nearest active
    layer is barred so the wall stays a continuous fence with no leak window.
    """
    barrier_top, barrier_bottom = band
    ca, cb = int(face.cell_a), int(face.cell_b)
    layers: list[int] = []
    dropped = 0
    overlaps = False
    for lay in range(nlay):
        intervals = (_layer_interval(lay, cell, top, botm) for cell in (ca, cb))
        if not any(bottom < barrier_top and above > barrier_bottom for bottom, above in intervals):
            continue
        overlaps = True
        if inactive[lay, ca] or inactive[lay, cb]:
            dropped += 1
            continue
        layers.append(lay)
    if overlaps:
        return layers, dropped, False
    lay = _nearest_active_layer_to_band(ca, cb, barrier_bottom, top, inactive, nlay)
    return ([] if lay is None else [lay]), 0, lay is not None


def build_flow_barrier_hfb(
    solver_mesh: SolverMesh,
    *,
    line: LineString,
    depths: list[float] | None = None,
    hydchr: float,
    crest_elevation: float | None = None,
    base_elevation: float | None = None,
    label: str = "flow barrier",
    qa: dict | None = None,
    faces: list[BarrierFace] | None = None,
    trace: LineString | None = None,
) -> list[list]:
    """Return HFB rows for a barrier line, over a depth or an absolute elevation band.

    The barrier top is ``crest_elevation`` (or the higher top of the two cells).
    The foot is either ``base_elevation`` (an absolute floor) or ``depths`` below
    the top (one value, or one per line vertex, interpolated at the vertices'
    arc-length stations). A layer is barred when its interval cuts the band at
    either cell of the link. MODFLOW 6 has no partial HFB: a barred layer is
    barred over its full thickness. A layer where a joined cell is inactive is
    skipped. Each face hydchr is weighted by L_trace / sum(L_faces).

    The barrier is not extended to the domain outline. A trace end that stops
    inside the domain leaves an open gap; it is logged as a WARNING with its
    length. ``qa``, when given, receives the faces per layer, the chain and
    trace lengths, the face weight, the open length at each end and the
    effective conductance per layer. Raises when the trace bars no interior
    face, and warns when every row was dropped for inactivity.

    The faces are those of :func:`barrier_faces_from_line`: the barrier family
    faces laid on *line*, or the faces it crosses on a staircase. ``faces``
    replaces them (a lake cutoff wall passes its shore faces); their ``s`` is
    then the position along ``trace``, the declared trace whose vertices carry
    the depths (*line* when ``trace`` is not given).
    """
    if faces is None:
        faces = barrier_faces_from_line(solver_mesh.cell_mesh, line)
    if not faces:
        raise ValueError(
            f"{label}: the trace crosses no interior mesh face. Check the trace CRS and "
            "coordinates and that it lies within the model extent and off the mesh edges."
        )
    stations = _vertex_stations(line if trace is None else trace)
    if base_elevation is None:
        n_vertices = int(stations.size)
        if depths is None or len(depths) not in (1, n_vertices):
            raise ValueError(
                f"{label}: depths must have 1 value or one per line vertex ({n_vertices})."
            )

    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    botm = np.asarray(solver_mesh.botm, dtype=float)
    inactive = np.asarray(solver_mesh.inactive_mask, dtype=bool)
    nlay = int(solver_mesh.nlay)

    footprint = mesh_footprint(solver_mesh.cell_mesh)
    trace_length = float(line.intersection(footprint).length)
    chain_length, weight = _trace_weight(faces, trace_length)
    face_hydchr = float(hydchr) * weight

    rows: list[list] = []
    faces_per_layer: dict[int, int] = {}
    conductance_per_layer: dict[int, float] = {}
    n_dropped = 0
    n_clamped = 0

    def _emit(lay: int, ca: int, cb: int, length: float) -> None:
        rows.append([(lay, ca), (lay, cb), face_hydchr])
        faces_per_layer[lay] = faces_per_layer.get(lay, 0) + 1
        thick = 0.0
        for cell in (ca, cb):
            bottom, layer_top = _layer_interval(lay, cell, top, botm)
            thick += 0.5 * max(layer_top - bottom, 0.0)
        conductance_per_layer[lay] = (
            conductance_per_layer.get(lay, 0.0) + face_hydchr * length * thick
        )

    for face in faces:
        band = _barrier_band(face, top, depths, stations, crest_elevation, base_elevation)
        layers, dropped, clamped = _face_layers(face, band, top, botm, inactive, nlay)
        n_dropped += dropped
        n_clamped += int(clamped)
        for lay in layers:
            _emit(lay, int(face.cell_a), int(face.cell_b), float(face.length))
    if n_dropped:
        logger.info("%s: %d HFB row(s) dropped over inactive cells.", label, n_dropped)
    if n_clamped:
        logger.info(
            "%s: %d face(s) sealed at the nearest layer where the band misses the aquifer "
            "(fence continuity).",
            label,
            n_clamped,
        )
    if not rows:
        logger.warning(
            "%s: resolves to %d face(s) but every layer joins an inactive cell; no HFB "
            "row was emitted.",
            label,
            len(faces),
        )

    gap_start, gap_end = trace_end_gaps(footprint, line)
    for name, gap in (("start", gap_start), ("end", gap_end)):
        if gap > 0.0:
            logger.warning(
                "%s: the trace %s stops %.1f m inside the domain; this gap stays open and "
                "flow can go around the barrier. The barrier is not extended.",
                label,
                name,
                gap,
            )
    summary = {
        "n_faces": len(faces),
        "faces_per_layer": dict(sorted(faces_per_layer.items())),
        "trace_length": trace_length,
        "chain_length": chain_length,
        "chain_over_trace": chain_length / trace_length if trace_length > 0 else float("nan"),
        "face_weight": weight,
        "hydchr": float(hydchr),
        "face_hydchr": face_hydchr,
        "open_length_start": gap_start,
        "open_length_end": gap_end,
        "effective_conductance": dict(sorted(conductance_per_layer.items())),
    }
    logger.info(
        "%s QA: faces per layer %s, chain/trace %.3f (face weight %.3f), open ends "
        "%.1f m / %.1f m, conductance per layer [m2/s] %s.",
        label,
        summary["faces_per_layer"],
        summary["chain_over_trace"],
        weight,
        gap_start,
        gap_end,
        {k: f"{v:.3g}" for k, v in summary["effective_conductance"].items()},
    )
    if qa is not None:
        qa.update(summary)
    return rows


def _barrier_attr(payload: object, name: str) -> object:
    """Read one key off a payload (a dict after binding, else a config object)."""
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


def _xt3d_active(model: object, solver_mesh: SolverMesh) -> bool:
    """Return True when XT3D is active for this model and mesh."""
    if getattr(model, "modflow_config", None) is None:
        return False
    return bool(xt3d_is_enabled(model, solver_mesh))


def _rows_for_barrier(
    model: object,
    solver_mesh: SolverMesh,
    cfg: object,
    line: LineString,
    label: str,
    *,
    faces: list[BarrierFace] | None = None,
    trace: LineString | None = None,
) -> list[list]:
    """HFB rows for one FlowBarrierConfig and its resolved shapely trace."""
    crest = getattr(cfg, "crest_elevation", None)
    base = getattr(cfg, "base_elevation", None)
    hydchr = float(cfg.effective_hydchr())
    if hydchr <= 0.0 and _xt3d_active(model, solver_mesh):
        raise ValueError(
            f"{label}: hydchr = {hydchr:g} is refused while XT3D is active. MODFLOW 6 "
            "ignores a zero hydchr and inverts a negative one under XT3D, so the wall "
            "would vanish. Set a small positive hydchr (e.g. 1e-12 1/s) or turn XT3D off."
        )
    return build_flow_barrier_hfb(
        solver_mesh,
        line=line,
        depths=None if cfg.depths is None else [float(d) for d in cfg.depths],
        hydchr=hydchr,
        crest_elevation=None if crest is None else float(crest),
        base_elevation=None if base is None else float(base),
        label=label,
        faces=faces,
        trace=trace,
    )


def _wall_trace(payload: object, line: LineString) -> LineString:
    """The declared trace of a lake wall, whose vertices carry the depths."""
    trace = _barrier_attr(payload, "cutoff_wall_trace")
    return line if trace is None else trace


def lake_wall_faces(
    solver_mesh: SolverMesh, payload: object, lake_cells: Sequence[int]
) -> list[BarrierFace]:
    """The faces of a lake cutoff wall bound on *payload*, positioned along its trace.

    With the lake cells, the wall hugs the lake cell set along the shore
    (:func:`cutoff_wall_faces`); without them (the lake is not modelled) it
    takes the faces of its line alone: the barrier family faces laid on it,
    or the faces it crosses on a staircase.
    """
    line = _barrier_attr(payload, "cutoff_wall_line")
    return cutoff_wall_faces(
        solver_mesh.cell_mesh,
        line,
        np.asarray(lake_cells, dtype=np.int64),
        _wall_trace(payload, line),
    )


def resolve_flow_barrier_hfb_rows(
    model: object,
    solver_mesh: SolverMesh,
    lake_cells_by_lake: Mapping[str, Sequence[int]] | None = None,
) -> list[list]:
    """Return concatenated HFB rows for every configured flow barrier.

    Two sources, both bound by the structure binders before pre-processing:
    each lake's dam ``cutoff_wall`` (wall on ``payload['cutoff_wall_line']``,
    laid on the lake shore) and the general ``[flow.sinks_sources.flow_barriers]``
    mapping (each payload is ``{'barrier': cfg, 'line': shapely}``). A lake wall
    bars the faces of :func:`lake_wall_faces` on the cells of
    ``lake_cells_by_lake``. Returns ``[]`` when none is configured, keeping the
    HFB wiring in ``build.py`` a no-op.
    """
    flow = getattr(model, "flow", None)
    if flow is None:
        return []
    sinks_sources = getattr(flow, "sinks_sources", {})
    if not isinstance(sinks_sources, Mapping):
        return []

    rows: list[list] = []

    lakes = sinks_sources.get("lakes")
    if isinstance(lakes, Mapping):
        for lake_id, payload in lakes.items():
            cfg = _barrier_attr(payload, "cutoff_wall")
            if cfg is None:
                continue
            line = _barrier_attr(payload, "cutoff_wall_line")
            if line is None:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id}.cutoff_wall is declared but its "
                    "trace was not resolved; bind it with apply_cutoff_wall_to_flow first."
                )
            cells = (lake_cells_by_lake or {}).get(str(lake_id), ())
            rows.extend(
                _rows_for_barrier(
                    model,
                    solver_mesh,
                    cfg,
                    line,
                    f"lake '{lake_id}' cutoff wall",
                    faces=lake_wall_faces(solver_mesh, payload, cells),
                    trace=_wall_trace(payload, line),
                )
            )

    barriers = sinks_sources.get("flow_barriers")
    if isinstance(barriers, Mapping):
        for barrier_id, payload in barriers.items():
            cfg = _barrier_attr(payload, "barrier")
            if cfg is None:
                continue
            line = _barrier_attr(payload, "line")
            if line is None:
                raise ValueError(
                    f"flow.sinks_sources.flow_barriers.{barrier_id} is declared but its "
                    "trace was not resolved; bind it with apply_flow_barriers_to_flow first."
                )
            rows.extend(
                _rows_for_barrier(model, solver_mesh, cfg, line, f"flow barrier '{barrier_id}'")
            )

    return rows


def check_cutoff_wall_seal(
    model: object,
    solver_mesh: SolverMesh,
    lake_cells_by_lake: Mapping[str, Sequence[int]],
    lake_connections: Sequence[Sequence[object]],
    hfb_rows: Sequence[Sequence[object]],
) -> None:
    """Refuse a lake cutoff wall that leaves the lake open past the dam.

    For each modelled lake with a wall: walking from the downstream side along
    the wall never reaches the lake side without crossing a wall face
    (:func:`wall_leaks`); no HORIZONTAL LAK connection reaches a cell downstream
    of the wall; every face between a lake cell and a downstream cell carries
    its HFB rows (the layers below the lake bed the wall reaches); and no wall
    face of the shore section joins two non-lake cells, which would leave a cell
    between the lake and the wall. Raises ``SolverInputError`` naming the lake
    and the counts.
    """
    flow = getattr(model, "flow", None)
    sinks_sources = getattr(flow, "sinks_sources", {}) if flow is not None else {}
    lakes = sinks_sources.get("lakes") if isinstance(sinks_sources, Mapping) else None
    if not isinstance(lakes, Mapping):
        return
    ifno = {lake_id: index for index, lake_id in enumerate(_active_lake_definitions(model))}
    rows = {(int(r[0][0]), *sorted((int(r[0][1]), int(r[1][1])))) for r in hfb_rows}
    for lake_id, payload in lakes.items():
        cfg = _barrier_attr(payload, "cutoff_wall")
        line = _barrier_attr(payload, "cutoff_wall_line")
        cells = np.asarray(lake_cells_by_lake.get(str(lake_id), ()), dtype=np.int64)
        if cfg is None or line is None or not cells.size or str(lake_id) not in ifno:
            continue
        counts = _wall_openings(
            solver_mesh, payload, cfg, cells, ifno[str(lake_id)], lake_connections, rows
        )
        if any(counts):
            raise SolverInputError(
                f"lake '{lake_id}' cutoff wall leaves the lake open past the dam: "
                f"{counts[0]} lake-side cell(s) reached from downstream, {counts[1]} "
                f"downstream cell(s) still in LAK bank connection, {counts[2]} lake "
                f"face(s) without their HFB rows, {counts[3]} cell(s) between the lake "
                "and the wall."
            )


def _wall_openings(
    solver_mesh: SolverMesh,
    payload: object,
    cfg: object,
    cells: np.ndarray,
    lake_index: int,
    lake_connections: Sequence[Sequence[object]],
    rows: set[tuple[int, int, int]],
) -> tuple[int, int, int, int]:
    """Leaks, unsealed bank connections, faces without HFB rows, cells between."""
    cell_mesh = solver_mesh.cell_mesh
    line = _barrier_attr(payload, "cutoff_wall_line")
    faces = lake_wall_faces(solver_mesh, payload, cells)
    reach = 3.0 * max((face.length for face in faces), default=0.0)
    leaks = wall_leaks(cell_mesh, line, cells, faces, reach=reach).size

    lake = np.zeros(cell_mesh.n_cells, dtype=bool)
    lake[cells] = True
    shore = {
        tuple(pair)
        for pair in cell_mesh.geometry.edge_cells[lake_shore_faces(cell_mesh, line, cells)].tolist()
    }
    downstream = {b if lake[a] else a for a, b in shore}
    connected = {
        int(row[2][1])
        for row in lake_connections
        if int(row[0]) == lake_index and row[3] == "HORIZONTAL"
    }

    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    botm = np.asarray(solver_mesh.botm, dtype=float)
    inactive = np.asarray(solver_mesh.inactive_mask, dtype=bool)
    trace = _wall_trace(payload, line)
    stations = _vertex_stations(trace)
    depths = None if cfg.depths is None else [float(d) for d in cfg.depths]
    crest, base = cfg.crest_elevation, cfg.base_elevation
    unbarred = 0
    for face in faces:
        if (face.cell_a, face.cell_b) not in shore:
            continue
        band = _barrier_band(face, top, depths, stations, crest, base)
        layers = _face_layers(face, band, top, botm, inactive, int(solver_mesh.nlay))[0]
        if any((lay, face.cell_a, face.cell_b) not in rows for lay in layers):
            unbarred += 1
    return (
        leaks,
        len(connected & downstream),
        unbarred,
        _cells_between(cell_mesh, payload, faces, lake),
    )


def _cells_between(
    cell_mesh: PlanarCellMesh,
    payload: object,
    faces: list[BarrierFace],
    lake: np.ndarray,
) -> int:
    """Non-lake cells on the lake side of wall faces along the shore section.

    A face counts when its midpoint falls on the shore section more than one
    cell size from either end: at a corner of the shore the cells round the
    corner, and the faces that close the fence there join bank cells.
    """
    line = _barrier_attr(payload, "cutoff_wall_line")
    shore = _barrier_attr(payload, "cutoff_wall_shore")
    if shore is None or shore.is_empty or not faces:
        return 0
    first = line.project(Point(shore.coords[0]))
    last = line.project(Point(shore.coords[-1]))
    geometry = cell_mesh.geometry
    pairs = np.array([(face.cell_a, face.cell_b) for face in faces], dtype=np.int64)
    size = np.sqrt(geometry.areas[pairs]).max(axis=1)
    edges = geometry.edge_between(pairs[:, 0], pairs[:, 1])
    along = shapely.line_locate_point(line, shapely.points(geometry.edge_midpoint[edges]))
    on_shore = (along > first + size) & (along < last - size)
    loose = pairs[on_shore & ~lake[pairs[:, 0]] & ~lake[pairs[:, 1]]].reshape(-1)
    if not loose.size:
        return 0
    upstream = ~downstream_of_wall(line, cell_mesh.centers[loose])
    return int(np.unique(loose[upstream]).size)

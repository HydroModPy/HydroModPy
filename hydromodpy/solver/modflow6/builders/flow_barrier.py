"""Build the MODFLOW 6 HFB (Horizontal Flow Barrier) stress-period data.

Turns the barrier faces a line crosses (``spatial.mesh.ops.flow_barrier``) into HFB
rows ``[(lay, cell_a), (lay, cell_b), hydchr]``, one per layer the barrier spans
from the model top down to a (possibly per-segment) depth. ``hydchr`` is the
barrier hydraulic characteristic = ``K_barrier / thickness`` [1/T]; a small value
is a near-impermeable wall (a dam cutoff wall / grout curtain).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders.solver_options import xt3d_is_enabled
from hydromodpy.spatial.mesh.ops.flow_barrier import (
    barrier_faces_from_line,
    mesh_footprint,
    trace_end_gaps,
)

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)


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
    effective conductance per layer. Raises when the trace crosses no interior
    face, and warns when every row was dropped for inactivity.
    """
    faces = barrier_faces_from_line(solver_mesh.cell_mesh, line)
    if not faces:
        raise ValueError(
            f"{label}: the trace crosses no interior mesh face. Check the trace CRS and "
            "coordinates and that it lies within the model extent and off the mesh edges."
        )
    stations = _vertex_stations(line)
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
        ca = int(face.cell_a)
        cb = int(face.cell_b)
        if crest_elevation is None:
            barrier_top = max(float(top[ca]), float(top[cb]))
        else:
            barrier_top = float(crest_elevation)
        if base_elevation is not None:
            barrier_bottom = float(base_elevation)
        else:
            barrier_bottom = barrier_top - _interp_depth(face.s, depths, stations)
        band_overlaps = False
        for lay in range(nlay):
            cuts = False
            for cell in (ca, cb):
                bottom, layer_top = _layer_interval(lay, cell, top, botm)
                if bottom < barrier_top and layer_top > barrier_bottom:
                    cuts = True
            if not cuts:
                continue
            band_overlaps = True
            if inactive[lay, ca] or inactive[lay, cb]:
                n_dropped += 1
                continue
            _emit(lay, ca, cb, float(face.length))
        if not band_overlaps:
            # The absolute band misses the aquifer entirely at this face (its bottom sits
            # above the crest, or its top below the foot -- the model bottom follows the
            # terrain, so a fixed band leaves the crest cells uncovered). Seal the nearest
            # active layer so the cutoff wall stays a continuous fence with no leak window.
            lay = _nearest_active_layer_to_band(ca, cb, barrier_bottom, top, inactive, nlay)
            if lay is not None:
                _emit(lay, ca, cb, float(face.length))
                n_clamped += 1
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
    model: object, solver_mesh: SolverMesh, cfg: object, line: LineString, label: str
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
    )


def resolve_flow_barrier_hfb_rows(model: object, solver_mesh: SolverMesh) -> list[list]:
    """Return concatenated HFB rows for every configured flow barrier.

    Two sources, both bound by the structure binders before pre-processing:
    each lake's dam ``cutoff_wall`` (trace on ``payload['cutoff_wall_line']``) and
    the general ``[flow.sinks_sources.flow_barriers]`` mapping (each payload is
    ``{'barrier': cfg, 'line': shapely}``). Returns ``[]`` when none is configured,
    keeping the HFB wiring in ``build.py`` a no-op.
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
            rows.extend(
                _rows_for_barrier(model, solver_mesh, cfg, line, f"lake '{lake_id}' cutoff wall")
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

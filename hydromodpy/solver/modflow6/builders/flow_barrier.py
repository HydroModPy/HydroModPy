"""Build the MODFLOW 6 HFB (Horizontal Flow Barrier) stress-period data.

Turns the barrier faces a line crosses (``spatial.mesh.flow_barrier``) into HFB
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
from hydromodpy.spatial.mesh.ops.flow_barrier import barrier_faces_from_line

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


def build_flow_barrier_hfb(
    solver_mesh: SolverMesh,
    *,
    line: LineString,
    depths: list[float] | None = None,
    hydchr: float,
    crest_elevation: float | None = None,
    base_elevation: float | None = None,
    label: str = "flow barrier",
) -> list[list]:
    """Return HFB rows for a barrier line, over a depth or an absolute elevation band.

    The barrier top is ``crest_elevation`` (or the cell top). The foot is either
    ``base_elevation`` (an absolute floor, blocking EVERY layer in the band -- a
    full-height impervious dam) or ``depths`` below the top (one value, or one per
    line vertex, interpolated at the vertices' arc-length stations). Each crossed
    face contributes its layers over that band, skipping any layer where a joined
    cell is inactive. Raises when the trace crosses no interior face, and warns
    when every row was dropped for inactivity.
    """
    faces = barrier_faces_from_line(solver_mesh.planar_mesh, line)
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

    rows: list[list] = []
    n_dropped = 0
    n_clamped = 0
    for face in faces:
        ca = int(face.cell_a)
        cb = int(face.cell_b)
        barrier_top = float(top[ca]) if crest_elevation is None else float(crest_elevation)
        if base_elevation is not None:
            barrier_bottom = float(base_elevation)
        else:
            barrier_bottom = barrier_top - _interp_depth(face.s, depths, stations)
        band_overlaps = False
        for lay in range(nlay):
            layer_top = float(top[ca]) if lay == 0 else float(botm[lay - 1, ca])
            layer_bottom = float(botm[lay, ca])
            if layer_bottom >= barrier_top:
                continue  # layer sits entirely above the barrier crest
            if layer_top <= barrier_bottom:
                break  # layer (and every deeper one) sits entirely below the barrier foot
            band_overlaps = True
            if inactive[lay, ca] or inactive[lay, cb]:
                n_dropped += 1
                continue
            rows.append([(lay, ca), (lay, cb), float(hydchr)])
        if not band_overlaps:
            # The absolute band misses the aquifer entirely at this face (its bottom sits
            # above the crest, or its top below the foot -- the model bottom follows the
            # terrain, so a fixed band leaves the crest cells uncovered). Seal the nearest
            # active layer so the cutoff wall stays a continuous fence with no leak window.
            lay = _nearest_active_layer_to_band(ca, cb, barrier_bottom, top, inactive, nlay)
            if lay is not None:
                rows.append([(lay, ca), (lay, cb), float(hydchr)])
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
    return rows


def _barrier_attr(payload: object, name: str) -> object:
    """Read one key off a payload (a dict after binding, else a config object)."""
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


def _rows_for_barrier(
    solver_mesh: SolverMesh, cfg: object, line: LineString, label: str
) -> list[list]:
    """HFB rows for one FlowBarrierConfig and its resolved shapely trace."""
    crest = getattr(cfg, "crest_elevation", None)
    base = getattr(cfg, "base_elevation", None)
    return build_flow_barrier_hfb(
        solver_mesh,
        line=line,
        depths=None if cfg.depths is None else [float(d) for d in cfg.depths],
        hydchr=cfg.effective_hydchr(),
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
            rows.extend(_rows_for_barrier(solver_mesh, cfg, line, f"lake '{lake_id}' cutoff wall"))

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
            rows.extend(_rows_for_barrier(solver_mesh, cfg, line, f"flow barrier '{barrier_id}'"))

    return rows

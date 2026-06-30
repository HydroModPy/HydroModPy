"""Build the MODFLOW 6 HFB (Horizontal Flow Barrier) stress-period data.

Turns the barrier faces a line crosses (``spatial.mesh.flow_barrier``) into HFB
rows ``[(lay, cell_a), (lay, cell_b), hydchr]``, one per layer the barrier spans
from the model top down to a (possibly per-segment) depth. ``hydchr`` is the
barrier hydraulic characteristic = ``K_barrier / thickness`` [1/T]; a small value
is a near-impermeable wall (a dam cutoff wall / grout curtain).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.spatial.mesh.flow_barrier import barrier_faces_from_line


def _interp_depth(s: float, depths: list[float]) -> float:
    """Interpolate a per-vertex depth list at the normalized line position s."""
    if len(depths) == 1:
        return float(depths[0])
    pos = max(0.0, min(1.0, s)) * (len(depths) - 1)
    lo = int(np.floor(pos))
    hi = min(lo + 1, len(depths) - 1)
    frac = pos - lo
    return float(depths[lo] * (1.0 - frac) + depths[hi] * frac)


def build_flow_barrier_hfb(
    solver_mesh,
    *,
    line,
    depths: list[float],
    hydchr: float,
) -> list[list]:
    """Return HFB rows for a barrier line carved to ``depths`` below the model top.

    ``depths`` is one value (uniform) or several (interpolated along the line per
    the crossing position). Each crossed face contributes the top layers down to
    the local depth. Returns ``[]`` when the line crosses no interior face.
    """
    faces = barrier_faces_from_line(solver_mesh.planar_mesh, line)
    if not faces:
        return []
    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1)
    botm = np.asarray(solver_mesh.botm, dtype=float)
    nlay = int(solver_mesh.nlay)

    rows: list[list] = []
    for face in faces:
        depth = _interp_depth(face.s, depths)
        c = face.cell_a
        barrier_bottom = float(top[c]) - float(depth)
        for lay in range(nlay):
            layer_top = float(top[c]) if lay == 0 else float(botm[lay - 1, c])
            if layer_top <= barrier_bottom:
                break
            rows.append([(lay, int(face.cell_a)), (lay, int(face.cell_b)), float(hydchr)])
    return rows


def _barrier_attr(payload: object, name: str) -> object:
    """Read one key off a payload (a dict after binding, else a config object)."""
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


def _rows_for_barrier(solver_mesh, cfg, line) -> list[list]:
    """HFB rows for one FlowBarrierConfig and its resolved shapely trace."""
    return build_flow_barrier_hfb(
        solver_mesh,
        line=line,
        depths=[float(d) for d in cfg.depths],
        hydchr=cfg.effective_hydchr(),
    )


def resolve_flow_barrier_hfb_rows(model, solver_mesh) -> list[list]:
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
            rows.extend(_rows_for_barrier(solver_mesh, cfg, line))

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
            rows.extend(_rows_for_barrier(solver_mesh, cfg, line))

    return rows

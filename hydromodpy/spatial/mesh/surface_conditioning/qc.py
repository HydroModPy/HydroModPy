"""Read-only drainage QC primitives on a mesh face graph.

These are the shared, solver-agnostic building blocks the diagnostic tool
(`tools/diagnostics/mesh_flow_qc.py`) and the conditioning tests both measure
with, so a "does the conditioned top drain?" check has one implementation. They
operate on plain arrays (top, active, adjacency, centroids, areas) plus the
control-cell set, never a SolverMesh or flopy. Pure numpy + math.
"""

from __future__ import annotations

import math

import numpy as np

_TOL_M = 1e-6

CLS_NORMAL, CLS_PIT, CLS_FLAT, CLS_BOUND, CLS_CONTROL = 0, 1, 2, 3, 4


def boundary_cells(active: np.ndarray, adjacency: list[set[int]]) -> set[int]:
    """Active cells with at least one inactive face neighbour (the outlet ring)."""
    active = np.asarray(active, dtype=bool).reshape(-1)
    out: set[int] = set()
    for cell in range(int(active.shape[0])):
        if not active[cell]:
            continue
        if any((not active[nb]) for nb in adjacency[cell]):
            out.add(cell)
    return out


def classify_depressions(
    top: np.ndarray,
    *,
    active: np.ndarray,
    adjacency: list[set[int]],
    xc: np.ndarray,
    yc: np.ndarray,
    boundary: set[int],
    control_cells: set[int] | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Classify each active cell: descent > flat > boundary > control > pit."""
    top = np.asarray(top, dtype=float).reshape(-1)
    active = np.asarray(active, dtype=bool).reshape(-1)
    xc = np.asarray(xc, dtype=float).reshape(-1)
    yc = np.asarray(yc, dtype=float).reshape(-1)
    control = set(control_cells or ())
    n = int(top.shape[0])
    cls = np.full(n, -1, dtype=int)
    for i in range(n):
        if not active[i] or not np.isfinite(top[i]):
            continue
        best_slope, best_j, eq = 0.0, -1, False
        for j in adjacency[i]:
            if not np.isfinite(top[j]):
                continue
            dz = top[i] - top[j]
            if abs(dz) < _TOL_M:
                eq = True
            elif dz > 0:
                dist = max(math.hypot(xc[i] - xc[j], yc[i] - yc[j]), 1.0)
                if dz / dist > best_slope:
                    best_slope, best_j = dz / dist, j
        if best_j >= 0:
            cls[i] = CLS_NORMAL
        elif eq:
            cls[i] = CLS_FLAT
        elif i in boundary:
            cls[i] = CLS_BOUND
        elif i in control:
            cls[i] = CLS_CONTROL
        else:
            cls[i] = CLS_PIT
    counts = {
        "pits": int((cls == CLS_PIT).sum()),
        "flats": int((cls == CLS_FLAT).sum()),
        "boundary_sinks": int((cls == CLS_BOUND).sum()),
        "control_minima": int((cls == CLS_CONTROL).sum()),
    }
    return cls, counts


def steepest_descent_accumulation(
    top: np.ndarray,
    *,
    active: np.ndarray,
    adjacency: list[set[int]],
    xc: np.ndarray,
    yc: np.ndarray,
    areas: np.ndarray,
    boundary: set[int],
    sink_cells: set[int] | None = None,
) -> dict:
    """SFD steepest-descent accumulation of cell areas (m2) on the mesh graph.

    ``sink_cells`` (lakes / control cells) terminate flow without a successor.
    Returns successor array, accumulated area, and a per-cell sink kind so the
    caller can close the mass budget (every area exits to a sink, the boundary,
    or is stranded in a pit/flat).
    """
    top = np.asarray(top, dtype=float).reshape(-1)
    active = np.asarray(active, dtype=bool).reshape(-1)
    xc = np.asarray(xc, dtype=float).reshape(-1)
    yc = np.asarray(yc, dtype=float).reshape(-1)
    areas = np.asarray(areas, dtype=float).reshape(-1)
    sinks = set(sink_cells or ())
    n = int(top.shape[0])
    succ = np.full(n, -1, dtype=int)
    sink_kind: dict[int, str] = {}
    n_flat_tie = 0
    for i in range(n):
        if not active[i]:
            continue
        if i in sinks:
            sink_kind[i] = "control"
            continue
        best_slope, best_j = 0.0, -1
        eq_lower_id = -1
        for j in adjacency[i]:
            dz = top[i] - top[j]
            if abs(dz) < _TOL_M:
                if j < i and (eq_lower_id < 0 or j < eq_lower_id):
                    eq_lower_id = j
            elif dz > 0:
                dist = max(math.hypot(xc[i] - xc[j], yc[i] - yc[j]), 1.0)
                if dz / dist > best_slope:
                    best_slope, best_j = dz / dist, j
        if best_j >= 0:
            succ[i] = best_j
        elif eq_lower_id >= 0:
            # Deterministic acyclic tie-break: equal-top neighbour with lower id.
            succ[i] = eq_lower_id
            n_flat_tie += 1
        elif i in boundary:
            sink_kind[i] = "boundary"
        else:
            sink_kind[i] = (
                "flat" if any(abs(top[i] - top[j]) < _TOL_M for j in adjacency[i]) else "pit"
            )

    acc = areas.copy()
    order = sorted(np.flatnonzero(active), key=lambda i: (top[i], i), reverse=True)
    for i in order:
        s = succ[i]
        if s >= 0:
            acc[s] += acc[i]
    return {"succ": succ, "acc": acc, "sink_kind": sink_kind, "n_flat_tie": n_flat_tie}


def accumulation_budget(flow: dict) -> dict[str, float]:
    """Close the accumulation budget from ``steepest_descent_accumulation`` output."""
    acc = flow["acc"]
    sink_kind = flow["sink_kind"]
    to_control = sum(float(acc[i]) for i, k in sink_kind.items() if k == "control")
    to_boundary = sum(float(acc[i]) for i, k in sink_kind.items() if k == "boundary")
    stranded = sum(float(acc[i]) for i, k in sink_kind.items() if k in ("pit", "flat"))
    return {
        "acc_control": to_control,
        "acc_boundary": to_boundary,
        "acc_stranded": stranded,
    }

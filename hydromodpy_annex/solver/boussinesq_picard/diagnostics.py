"""Shared math/geometry helpers and record types for the Picard/L-scheme runtimes."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from hydromodpy.solver.boussinesq.assembly.inputs import as_prescribed_head_cell_vector
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import SteadySolveInputs
from hydromodpy.solver.boussinesq.runtimes.execution_common import residual_norm_inf

DRY_THICKNESS_TOL_M = 1.0e-12
MIN_DISTANCE_M = 1.0e-12


@dataclass(frozen=True, kw_only=True)
class PicardLschemeOptions:
    """Options for the experimental strict bounded Picard/L-scheme solve."""

    picard_max_iterations: int = 500
    picard_tolerance_residual_inf: float = 1.0e-6
    picard_tolerance_update_inf: float = 1.0e-6
    picard_relaxation_omega: float = 0.5
    picard_omega_min: float = 0.05
    picard_lscheme_L: float | Literal["auto"] = "auto"
    picard_project_bounds: bool = True
    picard_final_vi_check: bool = False
    picard_fail_if_final_vi_fails: bool = False
    picard_output_diagnostics: bool = True
    picard_residual_growth_factor: float = 1.25
    picard_usable_residual_inf: float = 1.0e-3
    picard_top_n_cells: int = 500


@dataclass(frozen=True)
class PicardIterationRecord:
    """One persisted Picard iteration diagnostic row."""

    iteration: int
    omega: float
    Lstab: float
    residual_inf: float
    projected_residual_inf: float
    update_inf: float
    active_top_count: int
    active_bottom_count: int
    free_count: int
    physically_dry_count: int
    max_lower_violation: float
    max_upper_violation: float
    linear_solve_status: str
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class PicardViCycleOptions:
    """Options for strict Picard/VI cycling."""

    cycle_max: int = 10
    picard_steps_per_cycle: int = 200
    vi_max_iterations_per_cycle: int = 20
    accept_failed_vi_residual_factor: float = 0.5
    accept_failed_vi_if_bounds_ok: bool = True
    final_vi_required: bool = True
    output_diagnostics: bool = True
    picard_options: PicardLschemeOptions = field(
        default_factory=lambda: PicardLschemeOptions(
            picard_max_iterations=200,
            picard_relaxation_omega=1.0,
            picard_final_vi_check=False,
            picard_fail_if_final_vi_fails=False,
            picard_output_diagnostics=False,
        )
    )


@dataclass(frozen=True)
class PicardViCycleRecord:
    """One persisted Picard/VI cycle diagnostic row."""

    cycle: int
    start_residual_inf: float
    picard_iterations: int
    picard_residual_inf: float
    picard_stop_reason: str
    vi_attempted: bool
    vi_converged: bool
    vi_iterations: int
    vi_residual_inf: float
    vi_termination_reason: str
    vi_error: str
    accepted_source: str
    accepted_residual_inf: float
    active_top_count: int
    active_bottom_count: int
    free_count: int
    physically_dry_count: int
    note: str = ""


def physical_bounds(
    mesh: BoussinesqMesh,
    prescribed_head_m_by_cell: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return physical head bounds and the prescribed mask."""
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1).copy()
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    prescribed = np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask):
        pinned = np.clip(
            prescribed[prescribed_mask], lower[prescribed_mask], upper[prescribed_mask]
        )
        lower[prescribed_mask] = pinned
        upper[prescribed_mask] = pinned
    return lower, upper, prescribed_mask


def clip_head(
    head_m: np.ndarray,
    *,
    lower: np.ndarray,
    upper: np.ndarray,
    project_bounds: bool,
) -> np.ndarray:
    """Clip a head vector inside the (lower, upper) bounds when requested."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    if head.size != np.asarray(lower).size:
        raise ValueError(
            f"head_m length must match bounds ({int(head.size)} != {int(np.asarray(lower).size)})."
        )
    if not bool(project_bounds):
        return head
    return np.clip(head, np.asarray(lower, dtype=float), np.asarray(upper, dtype=float))


def prescribed_head_cells(
    prescribed_head_m_by_cell: np.ndarray | None,
    *,
    n_cells: int,
) -> np.ndarray:
    """Coerce prescribed heads to a (n_cells,) NaN-padded vector."""
    return as_prescribed_head_cell_vector(
        prescribed_head_m_by_cell,
        n_cells=int(n_cells),
        label="prescribed_head_m_by_cell",
    )


def obstacle_tolerance(inputs: SteadySolveInputs) -> float:
    """Return the tolerance used to classify active obstacle cells."""
    return max(1.0e-9, 10.0 * float(inputs.options.tol_state_update_inf))


def free_residual_norm(
    *,
    residual: np.ndarray,
    head: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> float:
    """Return the free-cell raw balance norm, excluding active obstacles."""
    head = np.asarray(head, dtype=float).reshape(-1)
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    interior = free & (head > lower + float(tol_h)) & (head < upper - float(tol_h))
    if not np.any(interior):
        return 0.0
    return residual_norm_inf(np.asarray(residual, dtype=float).reshape(-1)[interior])


def active_state(
    *,
    head: float,
    lower: float,
    upper: float,
    prescribed: bool,
    tol_h: float,
) -> str:
    """Return the active-state label for one cell."""
    if prescribed:
        return "prescribed"
    if head <= lower + tol_h:
        return "bottom"
    if head >= upper - tol_h:
        return "top"
    return "free"


def free_mask_from_bounds(
    *,
    head: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    tol_h: float,
) -> np.ndarray:
    """Return the boolean mask of cells strictly inside the bounds."""
    return (np.asarray(head) > np.asarray(lower) + tol_h) & (
        np.asarray(head) < np.asarray(upper) - tol_h
    )


def neighbor_counts(mesh: BoussinesqMesh) -> np.ndarray:
    """Return the number of internal-edge neighbors per cell."""
    counts = np.zeros(int(mesh.n_cells), dtype=int)
    for edge_index in range(int(mesh.n_edges)):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if 0 <= cell_a < counts.size and cell_b >= 0:
            counts[cell_a] += 1
        if 0 <= cell_b < counts.size:
            counts[cell_b] += 1
    return counts


def cell_id(mesh: BoussinesqMesh, index: int) -> int:
    """Return the cell_id at one mesh index."""
    values = getattr(mesh, "cell_ids", None)
    if values is None:
        return int(index)
    return int(np.asarray(values).reshape(-1)[index])


def cell_coord(mesh: BoussinesqMesh, index: int, names: tuple[str, ...]) -> float | None:
    """Return the first finite coordinate value found for the given attribute names."""
    for name in names:
        values = getattr(mesh, name, None)
        if values is None:
            continue
        array = np.asarray(values, dtype=float).reshape(-1)
        if index < array.size and np.isfinite(array[index]):
            return float(array[index])
    return None


def quantiles(values: np.ndarray) -> dict[str, float]:
    """Return a quantile summary dict for an array (NaN-safe)."""
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        return {key: math.nan for key in ("min", "p01", "p05", "p50", "p95", "p99", "max")}
    return {
        "min": float(np.min(array)),
        "p01": float(np.quantile(array, 0.01)),
        "p05": float(np.quantile(array, 0.05)),
        "p50": float(np.quantile(array, 0.50)),
        "p95": float(np.quantile(array, 0.95)),
        "p99": float(np.quantile(array, 0.99)),
        "max": float(np.max(array)),
    }


def jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/np arrays/scalars to JSON-safe Python values."""
    if hasattr(value, "__dataclass_fields__"):
        return {str(key): jsonable(item) for key, item in getattr(value, "__dict__", {}).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value

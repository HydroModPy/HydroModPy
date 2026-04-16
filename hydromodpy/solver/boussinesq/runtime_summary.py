"""Helpers that keep Boussinesq runtime summary bookkeeping out of the driver."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.solver.boussinesq.history_contract import build_transient_time_axes

if TYPE_CHECKING:
    from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
    from hydromodpy.solver.boussinesq.core.state import BoussinesqState
    from hydromodpy.solver.boussinesq.solver_contract import (
        BoussinesqSolverContract,
    )


_SECONDS_PER_DAY = 86_400.0
_SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S = 1.0e-12


def history_or_current(
    history_values: np.ndarray | None,
    current_values: np.ndarray | None,
    *,
    n_columns: int,
    default_value: float,
) -> np.ndarray:
    """Return one 2D history array from an optional history/current pair."""
    if history_values is not None:
        history = np.asarray(history_values, dtype=float)
        if history.ndim == 1:
            history = history.reshape(1, -1)
        if history.size != 0:
            return history
    if current_values is not None:
        current = np.asarray(current_values, dtype=float).reshape(1, -1)
        if current.size != 0:
            return current
    return np.full((1, int(n_columns)), float(default_value), dtype=float)


def elapsed_days_for_snapshots(
    state: "BoussinesqState | None",
    *,
    n_snapshots: int,
) -> np.ndarray:
    """Return one elapsed-time axis aligned with exported state snapshots."""
    count = max(int(n_snapshots), 1)
    elapsed_days = np.zeros(count, dtype=float)
    if state is None:
        return elapsed_days
    snapshot_elapsed_seconds = build_transient_time_axes(
        state.period_lengths_seconds
    ).snapshot_elapsed_seconds
    used_snapshots = min(snapshot_elapsed_seconds.size, count)
    if used_snapshots > 0:
        elapsed_days[:used_snapshots] = (
            snapshot_elapsed_seconds[:used_snapshots] / _SECONDS_PER_DAY
        )
        if used_snapshots < count:
            elapsed_days[used_snapshots:] = elapsed_days[used_snapshots - 1]
    return elapsed_days


def record_runtime_backend_summary(
    solver: "Boussinesq",
    contract: "BoussinesqSolverContract",
) -> None:
    """Record which nonlinear strategy was used for this solve."""
    options = solver._runtime_options()
    runtime_backend = contract.runtime_backend
    flow_regime = contract.flow_regime
    time_scheme = runtime_backend.method.time_scheme_for_regime(flow_regime)
    solver.runtime_summary["runtime_backend"] = runtime_backend.name
    solver.runtime_summary["runtime_engine"] = runtime_backend.name
    solver.runtime_summary["runtime_engine_id"] = runtime_backend.engine_id
    solver.runtime_summary["flow_regime"] = flow_regime
    solver.runtime_summary["runtime_backend_requested"] = (
        contract.runtime_backend_requested
    )
    solver.runtime_summary["surface_interaction_model_requested"] = (
        contract.surface_interaction_model_requested
    )
    solver.runtime_summary["surface_interaction_model_resolved"] = (
        contract.surface_interaction_model_resolved
    )
    solver.runtime_summary["runtime_solver_kind"] = (
        runtime_backend.nonlinear_solver_kind
    )
    solver.runtime_summary["runtime_linear_system_layout"] = (
        runtime_backend.linear_system_layout
    )
    solver.runtime_summary["runtime_jacobian_strategy"] = (
        runtime_backend.jacobian_strategy
    )
    solver.runtime_summary["runtime_linear_solver"] = (
        runtime_backend.linear_solver_kind
    )
    solver.runtime_summary["runtime_convergence_policy"] = (
        runtime_backend.convergence_policy
    )
    solver.runtime_summary["runtime_iteration_counter"] = (
        runtime_backend.iteration_counter_label
    )
    solver.runtime_summary["runtime_tol_residual_inf"] = float(
        options.tol_residual_inf
    )
    solver.runtime_summary["runtime_tol_state_update_inf"] = float(
        options.tol_state_update_inf
    )
    solver.runtime_summary["runtime_formulation"] = runtime_backend.method.id
    solver.runtime_summary["runtime_unknown_layout"] = (
        runtime_backend.method.unknown_layout
    )
    solver.runtime_summary["runtime_space_scheme"] = (
        runtime_backend.method.space_scheme_id
    )
    solver.runtime_summary["runtime_time_scheme"] = time_scheme.id
    solver.runtime_summary["runtime_problem_kind"] = time_scheme.problem_kind
    solver.runtime_summary["runtime_method_description"] = (
        runtime_backend.method.description
    )


def record_surface_threshold_summary(solver: "Boussinesq") -> None:
    """Record compact diagnostics about surface-threshold activation."""
    if solver.state is None or solver.mesh is None:
        return

    n_cells = int(solver.mesh.n_cells)
    head_history = history_or_current(
        solver.state.head_history_m,
        solver.state.head_m,
        n_columns=n_cells,
        default_value=0.0,
    )
    saturation_excess_history = history_or_current(
        solver.state.saturation_excess_history_m_s,
        solver.state.saturation_excess_rate_m_s,
        n_columns=n_cells,
        default_value=0.0,
    )

    n_snapshots = min(head_history.shape[0], saturation_excess_history.shape[0])
    head_history = np.asarray(head_history[:n_snapshots], dtype=float)
    saturation_excess_history = np.asarray(
        saturation_excess_history[:n_snapshots],
        dtype=float,
    )
    period_lengths = tuple(
        float(value)
        for value in (getattr(solver.state, "period_lengths_seconds", ()) or ())
    )
    evaluation_start = 1 if (n_snapshots > 1 and len(period_lengths) > 0) else 0
    evaluated_head_history = np.asarray(head_history[evaluation_start:], dtype=float)
    evaluated_saturation_excess_history = np.asarray(
        saturation_excess_history[evaluation_start:],
        dtype=float,
    )
    elapsed_days = elapsed_days_for_snapshots(solver.state, n_snapshots=n_snapshots)
    z_top = np.asarray(solver.mesh.z_top_m, dtype=float).reshape(1, -1)
    positive_saturation_excess = np.maximum(saturation_excess_history, 0.0)
    active_mask = positive_saturation_excess > _SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S
    active_counts = np.sum(active_mask, axis=1, dtype=int)
    active_any_by_snapshot = active_counts > 0
    activation_transitions = int(
        np.count_nonzero(
            active_any_by_snapshot
            & np.concatenate(([True], ~active_any_by_snapshot[:-1]))
        )
    )
    deactivation_transitions = int(
        np.count_nonzero(
            (~active_any_by_snapshot)
            & np.concatenate(([False], active_any_by_snapshot[:-1]))
        )
    )
    state_transitions = int(
        np.count_nonzero(active_any_by_snapshot[1:] != active_any_by_snapshot[:-1])
    )
    total_surface_flux_m3_day = (
        np.sum(
            positive_saturation_excess
            * np.asarray(solver.mesh.cell_area_m2, dtype=float)[None, :],
            axis=1,
        )
        * _SECONDS_PER_DAY
    )
    peak_active_cells = int(np.max(active_counts)) if active_counts.size else 0
    final_active_cells = int(active_counts[-1]) if active_counts.size else 0
    peak_head_above_top_m = float(
        np.max(evaluated_head_history - z_top) if evaluated_head_history.size else 0.0
    )
    active_indices = np.flatnonzero(active_counts > 0)
    first_active_index = int(active_indices[0]) if active_indices.size else None

    solver.runtime_summary["surface_threshold_active_rate_eps_m_s"] = float(
        _SURFACE_THRESHOLD_ACTIVE_RATE_EPS_M_S
    )
    solver.runtime_summary["surface_threshold_active_any"] = bool(
        active_indices.size > 0
    )
    solver.runtime_summary["surface_threshold_available_snapshots"] = int(n_snapshots)
    solver.runtime_summary["surface_threshold_evaluated_snapshots"] = int(
        evaluated_head_history.shape[0]
    )
    solver.runtime_summary["surface_threshold_last_snapshot_day"] = float(
        elapsed_days[-1] if elapsed_days.size else 0.0
    )
    solver.runtime_summary["surface_threshold_first_active_step"] = first_active_index
    solver.runtime_summary["surface_threshold_first_active_day"] = (
        None if first_active_index is None else float(elapsed_days[first_active_index])
    )
    solver.runtime_summary["surface_threshold_active_steps"] = int(
        np.count_nonzero(active_any_by_snapshot)
    )
    solver.runtime_summary["surface_threshold_activation_windows"] = int(
        activation_transitions
    )
    solver.runtime_summary["surface_threshold_deactivation_windows"] = int(
        deactivation_transitions
    )
    solver.runtime_summary["surface_threshold_state_transitions"] = int(
        state_transitions
    )
    solver.runtime_summary["surface_threshold_peak_active_cells"] = peak_active_cells
    solver.runtime_summary["surface_threshold_peak_active_fraction"] = float(
        peak_active_cells / max(n_cells, 1)
    )
    solver.runtime_summary["surface_threshold_final_active_cells"] = final_active_cells
    solver.runtime_summary["surface_threshold_final_active_fraction"] = float(
        final_active_cells / max(n_cells, 1)
    )
    solver.runtime_summary["surface_threshold_peak_cell_rate_mm_day"] = float(
        np.max(positive_saturation_excess) * _SECONDS_PER_DAY * 1_000.0
    )
    solver.runtime_summary["surface_threshold_peak_total_m3_day"] = float(
        np.max(total_surface_flux_m3_day) if total_surface_flux_m3_day.size else 0.0
    )
    solver.runtime_summary["surface_threshold_final_total_m3_day"] = float(
        total_surface_flux_m3_day[-1] if total_surface_flux_m3_day.size else 0.0
    )
    solver.runtime_summary["surface_threshold_peak_head_above_top_m"] = (
        peak_head_above_top_m
    )
    solver.runtime_summary["surface_threshold_any_head_above_top"] = bool(
        peak_head_above_top_m > 0.0
    )

    if solver._surface_interaction_model() != "complementarity":
        return

    top_gap_history_m = z_top - evaluated_head_history
    positive_gap = np.maximum(top_gap_history_m, 0.0)
    overlap = np.maximum(evaluated_saturation_excess_history, 0.0) * positive_gap
    solver.runtime_summary["surface_complementarity_min_gap_m"] = float(
        np.min(top_gap_history_m) if top_gap_history_m.size else 0.0
    )
    solver.runtime_summary["surface_complementarity_min_rate_m_s"] = float(
        np.min(evaluated_saturation_excess_history)
        if evaluated_saturation_excess_history.size
        else 0.0
    )
    solver.runtime_summary["surface_complementarity_peak_overlap_m2_s"] = float(
        np.max(overlap) if overlap.size else 0.0
    )
    solver.runtime_summary["surface_complementarity_final_overlap_m2_s"] = float(
        np.max(overlap[-1]) if overlap.size else 0.0
    )


__all__ = [
    "elapsed_days_for_snapshots",
    "history_or_current",
    "record_runtime_backend_summary",
    "record_surface_threshold_summary",
]

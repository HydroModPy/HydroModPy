"""Transient driver helpers for the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.solver.boussinesq.drivers.forcing import (
    apply_ocean_drainage_mask,
    resolve_runtime_forcing_by_period,
)
from hydromodpy.solver.boussinesq.drivers.state import (
    TransientRuntimeHistory,
    build_transient_activity_flags,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtime_summary import record_runtime_backend_summary

if TYPE_CHECKING:
    from hydromodpy.solver.boussinesq.boussinesq import Boussinesq


def _duration_seconds(value: object) -> float:
    """Return one duration in seconds from common Python/pandas/numpy payloads."""
    total_seconds = getattr(value, "total_seconds", None)
    if callable(total_seconds):
        return float(total_seconds())
    if isinstance(value, np.timedelta64):
        return float(value / np.timedelta64(1, "s"))
    if isinstance(value, timedelta):
        return float(value.total_seconds())
    return float(value)


def _period_lengths_from_boundaries(boundaries: object) -> tuple[float, ...]:
    """Derive positive period lengths from explicit time boundaries."""
    if boundaries is None:
        return ()
    items = tuple(boundaries)
    if len(items) < 2:
        return ()
    lengths: list[float] = []
    for start, end in zip(items[:-1], items[1:], strict=False):
        seconds = _duration_seconds(end - start)
        if seconds <= 0.0:
            return ()
        lengths.append(float(seconds))
    return tuple(lengths)


def _resolve_period_lengths_seconds(time_grid: object) -> tuple[float, ...]:
    """Resolve robust Boussinesq stress-period lengths from the launcher time grid."""
    raw_lengths = tuple(
        float(value) for value in (getattr(time_grid, "period_lengths_seconds", ()) or ())
    )
    if raw_lengths and all(value > 0.0 for value in raw_lengths):
        return raw_lengths

    from_boundaries = _period_lengths_from_boundaries(getattr(time_grid, "boundaries", None))
    if from_boundaries:
        return from_boundaries

    if raw_lengths:
        raise ValueError(
            "Boussinesq transient time grid contains non-positive period lengths "
            "and no valid boundaries fallback."
        )
    return ()


def _resolve_time_steps_per_period(time_grid: object) -> int:
    """Return the backward-Euler steps per stress period of the time grid.

    The grid carries ``[simulation.time].substeps_per_period`` as
    ``nstp_per_period``. A grid without it takes one step per period.
    """
    raw = getattr(time_grid, "nstp_per_period", None)
    if raw is None:
        return 1
    if isinstance(raw, bool) or int(raw) != raw or int(raw) < 1:
        raise ValueError(
            f"Boussinesq time grid nstp_per_period must be a positive integer, got {raw!r}."
        )
    return int(raw)


@dataclass
class _PeriodAdvance:
    """Outcome of the time steps of one stress period."""

    last_step: RuntimeSolveResult
    iterations: int
    converged: bool
    substep_details: list[dict[str, object]] = field(default_factory=list)
    ts_step_details: list[dict[str, object]] = field(default_factory=list)


def _tagged_details(raw: object, *, time_step_index: int | None) -> list[dict[str, object]]:
    """Copy one list of per-substep records, tagged with the time step index."""
    if not isinstance(raw, list):
        return []
    records: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        if time_step_index is not None:
            record["time_step_index"] = int(time_step_index)
        records.append(record)
    return records


def _advance_period(
    runtime_backend: Any,
    *,
    head_start_m: np.ndarray,
    period_seconds: float,
    n_steps: int,
    step_kwargs: dict[str, Any],
) -> _PeriodAdvance:
    """Advance one stress period in ``n_steps`` backward-Euler steps of equal length.

    The forcing of the period holds on every step, as in MODFLOW with
    ``tsmult = 1``. The advance stops at the first step that does not converge.
    """
    dt_seconds = float(period_seconds) / float(n_steps)
    head_m = np.asarray(head_start_m, dtype=float)
    iterations = 0
    substep_details: list[dict[str, object]] = []
    ts_step_details: list[dict[str, object]] = []
    step: RuntimeSolveResult | None = None
    for step_index in range(int(n_steps)):
        step = runtime_backend.solve_transient_step(
            TransientStepInputs(
                head_prev_m=head_m,
                dt_seconds=dt_seconds,
                head_initial_guess_m=head_m,
                **step_kwargs,
            )
        )
        iterations += int(step.iterations)
        tag = step_index if n_steps > 1 else None
        if step.diagnostics:
            substep_details.extend(
                _tagged_details(step.diagnostics.get("vi_substep_details"), time_step_index=tag)
            )
            ts_step_details.extend(
                _tagged_details(step.diagnostics.get("ts_vi_step_details"), time_step_index=tag)
            )
        head_m = np.asarray(step.head_m, dtype=float)
        if not step.converged:
            break
    if step is None:
        raise RuntimeError("Boussinesq period advance ran no time step.")
    return _PeriodAdvance(
        last_step=step,
        iterations=iterations,
        converged=bool(step.converged),
        substep_details=substep_details,
        ts_step_details=ts_step_details,
    )


def run_transient_runtime(solver: Boussinesq) -> bool:
    """Advance the head state over all launcher stress periods."""
    if solver.mesh is None:
        raise RuntimeError("Mesh must be built before running the runtime.")
    if solver.state is None:
        raise RuntimeError("Initial state must exist before time integration.")
    contract = solver._resolve_solver_contract()
    runtime_backend = contract.runtime_backend
    record_runtime_backend_summary(solver, contract)
    solver._assert_runtime_mesh_size_supported(runtime_backend)

    period_lengths = _resolve_period_lengths_seconds(solver.time_grid)
    if not period_lengths:
        return True
    n_steps = _resolve_time_steps_per_period(solver.time_grid)
    solver.runtime_summary["time_steps_per_period"] = int(n_steps)

    nper = len(period_lengths)
    runtime_forcing = resolve_runtime_forcing_by_period(solver, nper=nper)
    recharge_series_m_s = runtime_forcing.recharge_series_m_s
    well_flux_by_period_m3_s = runtime_forcing.well_flux_by_period_m3_s
    boundary_forcing = runtime_forcing
    dirichlet_supports_by_period = boundary_forcing.dirichlet_supports_by_period
    prescribed_heads_by_period = boundary_forcing.prescribed_heads_by_period
    boundary_heads_by_period = boundary_forcing.boundary_heads_by_period
    ocean_supported_cell_masks = boundary_forcing.ocean_supported_cell_masks
    drainage_conductance_series_m2_s = boundary_forcing.drainage_conductance_series_m2_s

    head_prev = np.asarray(solver.state.head_m, dtype=float)
    history = TransientRuntimeHistory.initialize(
        mesh=solver.mesh,
        head_m=head_prev,
        saturated_thickness_m=np.asarray(
            solver.state.saturated_thickness_m,
            dtype=float,
        ),
    )
    nonlinear_iterations: list[int] = []
    converged_by_period: list[bool] = []
    runtime_period_diagnostics: list[dict[str, object]] = []
    runtime_substep_diagnostics: list[dict[str, object]] = []
    runtime_ts_step_diagnostics: list[dict[str, object]] = []
    last_residual_norm = 0.0

    for kper, dt_seconds in enumerate(period_lengths):
        ocean_supported_cell_mask = np.asarray(
            ocean_supported_cell_masks[kper],
            dtype=bool,
        )
        drainage_conductance = apply_ocean_drainage_mask(
            n_cells=solver.mesh.n_cells,
            drainage_value_m2_s=float(drainage_conductance_series_m2_s[kper]),
            ocean_supported_cell_mask=ocean_supported_cell_mask,
        )
        advance = _advance_period(
            runtime_backend,
            head_start_m=head_prev,
            period_seconds=float(dt_seconds),
            n_steps=n_steps,
            step_kwargs={
                "mesh": solver.mesh,
                "recharge_rate_m_s": recharge_series_m_s[kper],
                "well_flux_m3_s": well_flux_by_period_m3_s[kper],
                "prescribed_head_m_by_cell": prescribed_heads_by_period[kper],
                "drainage_conductance_m2_s": drainage_conductance,
                "options": solver._runtime_options(),
            },
        )
        step = advance.last_step
        nonlinear_iterations.append(int(advance.iterations))
        converged_by_period.append(bool(advance.converged))
        head_prev = np.asarray(step.head_m, dtype=float)
        last_residual_norm = float(step.residual_norm_inf)
        solver.runtime_summary["last_termination_reason"] = str(step.termination_reason)
        if step.diagnostics:
            period_diagnostics = dict(step.diagnostics)
            period_diagnostics["period_index"] = int(kper)
            runtime_period_diagnostics.append(period_diagnostics)
            for key, value in step.diagnostics.items():
                solver.runtime_summary[f"last_{key}"] = value
        for item in advance.substep_details:
            item["period_index"] = int(kper)
            runtime_substep_diagnostics.append(item)
        for item in advance.ts_step_details:
            item["period_index"] = int(kper)
            runtime_ts_step_diagnostics.append(item)
        history.append_step(
            mesh=solver.mesh,
            head_m=head_prev,
            assembly=step.assembly,
            prescribed_head_m_by_cell=np.asarray(
                prescribed_heads_by_period[kper],
                dtype=float,
            ),
            boundary_head_m_by_edge=np.asarray(
                boundary_heads_by_period[kper],
                dtype=float,
            ),
        )
        if not advance.converged:
            solver.state = history.build_runtime_state(
                period_lengths_seconds=period_lengths,
                nonlinear_iterations=tuple(nonlinear_iterations),
                converged_by_period=tuple(converged_by_period),
            )
            solver.runtime_summary["last_residual_norm_inf"] = last_residual_norm
            solver.runtime_summary["n_periods"] = nper
            if runtime_period_diagnostics:
                solver.runtime_summary["runtime_period_diagnostics"] = runtime_period_diagnostics
            if runtime_substep_diagnostics:
                solver.runtime_summary["runtime_substep_diagnostics"] = runtime_substep_diagnostics
            if runtime_ts_step_diagnostics:
                solver.runtime_summary["runtime_ts_step_diagnostics"] = runtime_ts_step_diagnostics
            solver.runtime_summary.update(
                build_transient_activity_flags(
                    recharge_series_m_s=recharge_series_m_s,
                    well_flux_by_period_m3_s=well_flux_by_period_m3_s,
                    dirichlet_supports_by_period=dirichlet_supports_by_period,
                    prescribed_heads_by_period=prescribed_heads_by_period,
                    ocean_supported_cell_masks=ocean_supported_cell_masks,
                    drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
                )
            )
            return False

    solver.state = history.build_runtime_state(
        period_lengths_seconds=period_lengths,
        nonlinear_iterations=tuple(nonlinear_iterations),
        converged_by_period=tuple(converged_by_period),
    )
    solver.runtime_summary["n_periods"] = nper
    solver.runtime_summary["last_residual_norm_inf"] = last_residual_norm
    if runtime_period_diagnostics:
        solver.runtime_summary["runtime_period_diagnostics"] = runtime_period_diagnostics
    if runtime_substep_diagnostics:
        solver.runtime_summary["runtime_substep_diagnostics"] = runtime_substep_diagnostics
    if runtime_ts_step_diagnostics:
        solver.runtime_summary["runtime_ts_step_diagnostics"] = runtime_ts_step_diagnostics
    solver.runtime_summary.update(
        build_transient_activity_flags(
            recharge_series_m_s=recharge_series_m_s,
            well_flux_by_period_m3_s=well_flux_by_period_m3_s,
            dirichlet_supports_by_period=dirichlet_supports_by_period,
            prescribed_heads_by_period=prescribed_heads_by_period,
            ocean_supported_cell_masks=ocean_supported_cell_masks,
            drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
        )
    )
    return True


__all__ = ["run_transient_runtime"]

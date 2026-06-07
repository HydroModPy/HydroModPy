"""Common helpers shared by head-only Boussinesq runtimes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_steady_residual,
    assemble_transient_residual,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    SteadySolveInputs,
    TransientStepInputs,
)


@dataclass(frozen=True)
class HeadOnlyAssemblyCallback:
    """Normalized solve view shared by head-only Boussinesq runtimes."""

    head_initial_guess_m: np.ndarray
    options: object
    assembly_for: Callable[[np.ndarray], BoussinesqAssembly]
    prescribed_head_m_by_cell: np.ndarray | None


def _prescribed_head_cells(
    prescribed_head_m_by_cell: np.ndarray | None,
) -> np.ndarray | None:
    """Return the canonical prescribed-head runtime input."""
    if prescribed_head_m_by_cell is None:
        return None
    return np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)


def build_transient_assembly_callback(
    inputs: TransientStepInputs,
) -> HeadOnlyAssemblyCallback:
    """Return initial head guess, options and assembly callback for one transient step."""
    if float(inputs.dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")

    head_prev = np.asarray(inputs.head_prev_m, dtype=float)
    head_initial = (
        head_prev.copy()
        if inputs.head_initial_guess_m is None
        else np.asarray(inputs.head_initial_guess_m, dtype=float).copy()
    )
    options = inputs.options
    prescribed_head_m_by_cell = _prescribed_head_cells(inputs.prescribed_head_m_by_cell)

    def _assembly_for(candidate_head: np.ndarray) -> BoussinesqAssembly:
        return assemble_transient_residual(
            inputs.mesh,
            head_m=candidate_head,
            head_prev_m=head_prev,
            dt_seconds=float(inputs.dt_seconds),
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(options.regularization_radius),
        )

    return HeadOnlyAssemblyCallback(
        head_initial_guess_m=head_initial,
        options=options,
        assembly_for=_assembly_for,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )


def build_steady_assembly_callback(
    inputs: SteadySolveInputs,
    *,
    head_transform: Callable[[np.ndarray], np.ndarray] | None = None,
) -> HeadOnlyAssemblyCallback:
    """Return initial head guess, options and assembly callback for one steady solve."""
    head_initial = np.asarray(inputs.head_initial_guess_m, dtype=float).copy()
    if head_transform is not None:
        head_initial = np.asarray(head_transform(head_initial), dtype=float).copy()
    options = inputs.options
    prescribed_head_m_by_cell = _prescribed_head_cells(inputs.prescribed_head_m_by_cell)

    def _assembly_for(candidate_head: np.ndarray) -> BoussinesqAssembly:
        return assemble_steady_residual(
            inputs.mesh,
            head_m=candidate_head,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(options.regularization_radius),
        )

    return HeadOnlyAssemblyCallback(
        head_initial_guess_m=head_initial,
        options=options,
        assembly_for=_assembly_for,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )


__all__ = [
    "HeadOnlyAssemblyCallback",
    "build_steady_assembly_callback",
    "build_transient_assembly_callback",
]

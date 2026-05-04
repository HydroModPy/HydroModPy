from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hydromodpy.solver.boussinesq.assembly import BoussinesqAssembly
from hydromodpy.solver.boussinesq.runtimes.petsc_mixed import (
    _assembly_with_dry_deficit,
    _clip_free_head_to_obstacles,
    _split_double_obstacle_state,
    _stack_double_obstacle_state,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_mixed_common import (
    _fischer_burmeister_residual_and_derivatives,
    _fischer_burmeister_residual_and_gap_derivatives,
)


@dataclass
class _MiniMesh:
    cell_area_m2: np.ndarray
    z_top_m: np.ndarray
    z_bottom_m: np.ndarray

    @property
    def n_cells(self) -> int:
        return int(self.cell_area_m2.size)


def _assembly(residual_m3_s: np.ndarray) -> BoussinesqAssembly:
    zeros_cells = np.zeros_like(residual_m3_s, dtype=float)
    return BoussinesqAssembly(
        head_m=zeros_cells.copy(),
        saturated_thickness_m=zeros_cells.copy(),
        transmissivity_m2_s=zeros_cells.copy(),
        recharge_rate_m_s=zeros_cells.copy(),
        well_flux_m3_s=zeros_cells.copy(),
        saturation_excess_rate_m_s=zeros_cells.copy(),
        internal_edge_flux_m3_s=np.asarray([], dtype=float),
        prescribed_head_flux_m3_s=zeros_cells.copy(),
        prescribed_head_m_by_cell=np.full(residual_m3_s.size, np.nan, dtype=float),
        boundary_edge_flux_m3_s=np.asarray([], dtype=float),
        drainage_flux_m3_s=zeros_cells.copy(),
        residual_m3_s=np.asarray(residual_m3_s, dtype=float),
        head_constraint_residual_m=zeros_cells.copy(),
        flow_residual_m3_s=np.asarray(residual_m3_s, dtype=float),
        solver_residual=np.asarray(residual_m3_s, dtype=float),
    )


def test_fischer_burmeister_gap_derivative_matches_surface_sign_convention() -> None:
    rate = np.asarray([0.2], dtype=float)
    gap = np.asarray([0.3], dtype=float)
    head_scale_m = 2.0
    rate_scale_m_s = 0.5

    _, surface_dh, surface_dq = _fischer_burmeister_residual_and_derivatives(
        rate,
        gap,
        head_scale_m=head_scale_m,
        rate_scale_m_s=rate_scale_m_s,
    )
    _, gap_derivative, gap_dq = _fischer_burmeister_residual_and_gap_derivatives(
        rate,
        gap,
        head_scale_m=head_scale_m,
        rate_scale_m_s=rate_scale_m_s,
    )

    np.testing.assert_allclose(surface_dh, -gap_derivative)
    np.testing.assert_allclose(surface_dq, gap_dq)


def test_dry_deficit_reduces_only_free_cell_balance_residual() -> None:
    mesh = _MiniMesh(
        cell_area_m2=np.asarray([2.0, 3.0], dtype=float),
        z_top_m=np.asarray([1.0, 1.0], dtype=float),
        z_bottom_m=np.asarray([0.0, 0.0], dtype=float),
    )
    assembly = _assembly(np.asarray([5.0, 7.0], dtype=float))

    with_dry = _assembly_with_dry_deficit(
        mesh,
        assembly,
        np.asarray([1.5, 2.0], dtype=float),
        prescribed_mask=np.asarray([False, True], dtype=bool),
    )

    np.testing.assert_allclose(with_dry.residual_m3_s, np.asarray([2.0, 7.0]))
    np.testing.assert_allclose(assembly.residual_m3_s, np.asarray([5.0, 7.0]))


def test_double_obstacle_state_pack_unpack_roundtrip() -> None:
    state = _stack_double_obstacle_state(
        np.asarray([1.0, 2.0], dtype=float),
        np.asarray([0.1, 0.2], dtype=float),
        np.asarray([0.3, 0.4], dtype=float),
    )

    head, q_ex, q_dry = _split_double_obstacle_state(state, n_cells=2)

    np.testing.assert_allclose(head, np.asarray([1.0, 2.0]))
    np.testing.assert_allclose(q_ex, np.asarray([0.1, 0.2]))
    np.testing.assert_allclose(q_dry, np.asarray([0.3, 0.4]))


def test_initial_guess_clips_only_free_heads_to_obstacles() -> None:
    mesh = _MiniMesh(
        cell_area_m2=np.asarray([1.0, 1.0, 1.0], dtype=float),
        z_top_m=np.asarray([2.0, 2.0, 2.0], dtype=float),
        z_bottom_m=np.asarray([0.0, 0.0, 0.0], dtype=float),
    )

    clipped = _clip_free_head_to_obstacles(
        mesh,
        np.asarray([-1.0, 3.0, -2.0], dtype=float),
        prescribed_mask=np.asarray([False, False, True], dtype=bool),
    )

    np.testing.assert_allclose(clipped, np.asarray([0.0, 2.0, -2.0]))

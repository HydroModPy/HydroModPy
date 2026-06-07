"""Validate lower-obstacle drying behavior in the PETSc complementarity runtime."""

from __future__ import annotations

import platform
from dataclasses import dataclass

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_mixed import solve_transient_step


def _require_linux_petsc4py() -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")


@dataclass
class _MiniMesh:
    cell_area_m2: np.ndarray
    z_top_m: np.ndarray
    z_bottom_m: np.ndarray
    hydraulic_conductivity_m_s: np.ndarray
    storage_coefficient: np.ndarray
    edge_ids: np.ndarray
    edge_cell_a: np.ndarray
    edge_cell_b: np.ndarray
    edge_length_m: np.ndarray
    edge_distance_m: np.ndarray
    edge_midpoint_distance_to_cell_a_m: np.ndarray
    edge_midpoint_distance_to_cell_b_m: np.ndarray

    @property
    def n_cells(self) -> int:
        return int(self.cell_area_m2.size)

    @property
    def n_edges(self) -> int:
        return int(self.edge_ids.size)


def _single_cell_mesh() -> _MiniMesh:
    return _MiniMesh(
        cell_area_m2=np.asarray([1.0], dtype=float),
        z_top_m=np.asarray([2.0], dtype=float),
        z_bottom_m=np.asarray([0.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0], dtype=float),
        storage_coefficient=np.asarray([0.2], dtype=float),
        edge_ids=np.asarray([], dtype=int),
        edge_cell_a=np.asarray([], dtype=int),
        edge_cell_b=np.asarray([], dtype=int),
        edge_length_m=np.asarray([], dtype=float),
        edge_distance_m=np.asarray([], dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.asarray([], dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.asarray([], dtype=float),
    )


def _sloping_hillslope_mesh(n_cells: int = 8) -> _MiniMesh:
    edge_ids = np.arange(n_cells - 1, dtype=int)
    z_bottom = np.linspace(20.0, 0.0, n_cells, dtype=float)
    return _MiniMesh(
        cell_area_m2=np.full(n_cells, 100.0, dtype=float),
        z_top_m=z_bottom + 1.5,
        z_bottom_m=z_bottom,
        hydraulic_conductivity_m_s=np.full(n_cells, 1.0e-3, dtype=float),
        storage_coefficient=np.full(n_cells, 0.2, dtype=float),
        edge_ids=edge_ids,
        edge_cell_a=edge_ids.copy(),
        edge_cell_b=edge_ids + 1,
        edge_length_m=np.full(n_cells - 1, 10.0, dtype=float),
        edge_distance_m=np.full(n_cells - 1, 10.0, dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.full(n_cells - 1, 5.0, dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.full(n_cells - 1, 5.0, dtype=float),
    )


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.petsc
def test_single_cell_pumping_activates_lower_obstacle() -> None:
    _require_linux_petsc4py()
    mesh = _single_cell_mesh()

    result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray([0.1], dtype=float),
            dt_seconds=10.0,
            head_initial_guess_m=np.asarray([0.1], dtype=float),
            recharge_rate_m_s=0.0,
            well_flux_m3_s=np.asarray([-0.01], dtype=float),
            options=NonlinearRuntimeOptions(
                regularization_radius=0.05,
                max_iterations=30,
                tol_residual_inf=1.0e-10,
            ),
        )
    )

    assert result.converged is True
    assert result.residual_norm_inf <= 1.0e-10
    np.testing.assert_allclose(result.head_m, mesh.z_bottom_m, atol=1.0e-12)
    np.testing.assert_allclose(result.assembly.dry_deficit_rate_m_s, [0.008], atol=1.0e-12)
    np.testing.assert_allclose(result.assembly.saturation_excess_rate_m_s, [0.0], atol=1.0e-12)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.petsc
def test_steep_sloping_hillslope_zero_recharge_dries_then_rewets() -> None:
    _require_linux_petsc4py()
    mesh = _sloping_hillslope_mesh()
    options = NonlinearRuntimeOptions(
        regularization_radius=0.05,
        max_iterations=80,
        tol_residual_inf=1.0e-8,
    )
    prescribed_head = np.full(mesh.n_cells, np.nan, dtype=float)
    prescribed_head[-1] = mesh.z_bottom_m[-1]

    head = mesh.z_bottom_m + 1.0
    first_dry_result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=head,
            dt_seconds=30.0 * 86_400.0,
            head_initial_guess_m=head,
            recharge_rate_m_s=0.0,
            well_flux_m3_s=np.zeros(mesh.n_cells, dtype=float),
            prescribed_head_m_by_cell=prescribed_head,
            options=options,
        )
    )
    assert first_dry_result.converged is True
    assert np.max(first_dry_result.head_m - mesh.z_bottom_m) < 0.1
    assert np.count_nonzero(first_dry_result.assembly.dry_deficit_rate_m_s > 1.0e-12) >= 1

    second_dry_result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=first_dry_result.head_m,
            dt_seconds=30.0 * 86_400.0,
            head_initial_guess_m=first_dry_result.head_m,
            recharge_rate_m_s=0.0,
            well_flux_m3_s=np.zeros(mesh.n_cells, dtype=float),
            prescribed_head_m_by_cell=prescribed_head,
            options=options,
        )
    )
    assert second_dry_result.converged is True
    assert second_dry_result.residual_norm_inf <= 1.0e-8
    assert np.min(second_dry_result.head_m - mesh.z_bottom_m) >= -1.0e-8
    assert np.max(second_dry_result.head_m - mesh.z_bottom_m) < np.max(
        first_dry_result.head_m - mesh.z_bottom_m
    )
    assert np.count_nonzero(second_dry_result.assembly.dry_deficit_rate_m_s > 1.0e-12) >= 3
    assert second_dry_result.assembly.dry_deficit_rate_m_s[-1] == pytest.approx(0.0)

    rewetting_result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=second_dry_result.head_m,
            dt_seconds=10.0 * 86_400.0,
            head_initial_guess_m=second_dry_result.head_m,
            recharge_rate_m_s=2.0e-6,
            well_flux_m3_s=np.zeros(mesh.n_cells, dtype=float),
            prescribed_head_m_by_cell=prescribed_head,
            options=options,
        )
    )

    assert rewetting_result.converged is True
    assert rewetting_result.residual_norm_inf <= 1.0e-8
    assert np.max(rewetting_result.head_m - mesh.z_bottom_m) > 0.5
    assert np.count_nonzero(rewetting_result.assembly.dry_deficit_rate_m_s > 1.0e-12) == 0

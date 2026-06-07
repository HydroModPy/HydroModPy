from __future__ import annotations

import numpy as np
import pytest

import hydromodpy.solver.boussinesq.runtimes.petsc_vi_obstacle as vi_runtime
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    SteadySolveInputs,
)
from hydromodpy.solver.boussinesq.runtimes.dry_equilibrium import (
    assemble_effective_steady_balance,
    detect_dry_equilibrium,
    effective_saturated_thickness,
    physical_saturated_thickness,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi_obstacle import solve_steady_problem
from tests._helpers.mesh_doubles import _MiniMesh, line_mesh


def _mesh(z_bottom: list[float], *, k_m_s: float = 1.0e-5) -> _MiniMesh:
    return line_mesh(z_bottom, k_m_s=k_m_s)


def test_single_cell_zero_recharge_is_dry_equilibrium_without_floor() -> None:
    mesh = _mesh([0.0])

    result = detect_dry_equilibrium(mesh, recharge_rate_m_s=0.0)

    assert result.detected is True
    assert result.rejected_reason is None
    np.testing.assert_allclose(result.head_m, mesh.z_bottom_m)
    assert result.diagnostics["cells_physically_dry_count"] == 1
    assert result.diagnostics["effective_saturated_thickness_min"] == pytest.approx(0.0)
    assert result.vi_violations_count == 0


def test_single_cell_zero_recharge_with_bmin_keeps_physical_dry_state() -> None:
    mesh = _mesh([0.0])

    result = detect_dry_equilibrium(
        mesh,
        recharge_rate_m_s=0.0,
        minimum_saturated_thickness_m=0.10,
    )

    assert result.detected is True
    assert result.diagnostics["physical_saturated_thickness_min"] == pytest.approx(0.0)
    assert result.diagnostics["effective_saturated_thickness_min"] == pytest.approx(0.10)
    np.testing.assert_allclose(physical_saturated_thickness(mesh, result.head_m), [0.0])
    np.testing.assert_allclose(
        effective_saturated_thickness(mesh, result.head_m, minimum_saturated_thickness_m=0.10),
        [0.10],
    )


def test_two_cells_flat_bottom_with_bmin_has_no_film_flux() -> None:
    mesh = _mesh([0.0, 0.0])

    result = detect_dry_equilibrium(mesh, minimum_saturated_thickness_m=0.10)

    assert result.detected is True
    np.testing.assert_allclose(result.internal_edge_flux_m3_s, [0.0])
    assert result.projected_residual_inf == pytest.approx(0.0)


def test_two_cells_sloping_bottom_without_bmin_has_zero_flux_and_is_admissible() -> None:
    mesh = _mesh([1.0, 0.0])

    result = detect_dry_equilibrium(mesh, minimum_saturated_thickness_m=0.0)

    assert result.detected is True
    np.testing.assert_allclose(result.internal_edge_flux_m3_s, [0.0])
    assert result.projected_residual_inf == pytest.approx(0.0)


def test_two_cells_sloping_bottom_with_bmin_documents_film_flux() -> None:
    mesh = _mesh([1.0, 0.0])

    result = detect_dry_equilibrium(mesh, minimum_saturated_thickness_m=0.10)
    balance = assemble_effective_steady_balance(
        mesh,
        mesh.z_bottom_m,
        minimum_saturated_thickness_m=0.10,
    )

    assert result.detected is False
    assert result.rejected_reason == "lower-bound VI residual is negative"
    assert result.vi_violations_count == 1
    assert float(np.max(np.abs(balance.internal_edge_flux_m3_s))) == pytest.approx(1.0e-6)
    assert result.diagnostics["cells_physically_dry_count"] == 2
    assert result.diagnostics["cells_at_effective_floor_count"] == 2


def test_positive_recharge_rejects_dry_equilibrium() -> None:
    mesh = _mesh([0.0])

    result = detect_dry_equilibrium(mesh, recharge_rate_m_s=1.0e-10)

    assert result.detected is False
    assert result.positive_forcing_detected is True
    assert result.rejected_reason == "positive recharge present"


def test_prescribed_head_above_bottom_rejects_dry_equilibrium() -> None:
    mesh = _mesh([0.0])

    result = detect_dry_equilibrium(
        mesh,
        recharge_rate_m_s=0.0,
        prescribed_head_m_by_cell=np.asarray([1.0], dtype=float),
    )

    assert result.detected is False
    assert result.positive_forcing_detected is True
    assert result.rejected_reason == "prescribed head above bottom present"


def test_steady_vi_runtime_returns_detected_dry_equilibrium_without_petsc() -> None:
    mesh = _mesh([0.0, 0.0])

    result = solve_steady_problem(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.asarray([5.0, 5.0], dtype=float),
            recharge_rate_m_s=0.0,
            options=NonlinearRuntimeOptions(
                regularization_radius=0.05,
                max_iterations=20,
                tol_residual_inf=1.0e-12,
            ),
        )
    )

    assert result.converged is True
    assert result.iterations == 0
    assert result.termination_reason == "dry equilibrium detected before PETSc SNESVI"
    np.testing.assert_allclose(result.head_m, mesh.z_bottom_m)
    assert result.diagnostics is not None
    assert result.diagnostics["dry_equilibrium_detected"] is True
    assert result.diagnostics["snes_converged_reason_label"] == "DRY_EQUILIBRIUM_DETECTED"


def test_steady_vi_runtime_does_not_short_circuit_positive_recharge(monkeypatch) -> None:
    mesh = _mesh([0.0])

    def fake_solver(**_kwargs):
        raise RuntimeError("SNESVI path called")

    monkeypatch.setattr(vi_runtime, "_solve_vi_obstacle_problem", fake_solver)

    with pytest.raises(RuntimeError, match="SNESVI path called"):
        vi_runtime.solve_steady_problem(
            SteadySolveInputs(
                mesh=mesh,
                head_initial_guess_m=np.asarray([0.0], dtype=float),
                recharge_rate_m_s=1.0e-10,
                options=NonlinearRuntimeOptions(
                    regularization_radius=0.05,
                    max_iterations=20,
                    tol_residual_inf=1.0e-6,
                ),
            )
        )

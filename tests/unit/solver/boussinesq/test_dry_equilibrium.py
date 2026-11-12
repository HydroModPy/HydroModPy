"""Dry equilibrium of a Boussinesq aquifer without recharge (heads in m, fluxes in m3/s).

With no forcing the water table rests on the bottom. A minimum saturated thickness
keeps a film that can still carry flux, and the stationary VI solve skips PETSc
when it finds the dry state.
"""

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
from tests._helpers.boussinesq_mesh_doubles import _MiniMesh, line_mesh


def _mesh(z_bottom: list[float], *, k_m_s: float = 1.0e-5) -> _MiniMesh:
    return line_mesh(z_bottom, k_m_s=k_m_s)


def test_one_cell_without_floor() -> None:
    mesh = _mesh([0.0])

    result = detect_dry_equilibrium(mesh, recharge_rate_m_s=0.0)

    assert result.detected is True
    assert result.rejected_reason is None
    np.testing.assert_allclose(result.head_m, mesh.z_bottom_m)
    assert result.diagnostics["cells_physically_dry_count"] == 1
    assert result.diagnostics["effective_saturated_thickness_min"] == pytest.approx(0.0)
    assert result.vi_violations_count == 0


def test_one_cell_with_floor() -> None:
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


def test_flat_bottom_with_floor() -> None:
    mesh = _mesh([0.0, 0.0])

    result = detect_dry_equilibrium(mesh, minimum_saturated_thickness_m=0.10)

    assert result.detected is True
    np.testing.assert_allclose(result.internal_edge_flux_m3_s, [0.0])
    assert result.projected_residual_inf == pytest.approx(0.0)


def test_sloping_bottom_without_floor() -> None:
    mesh = _mesh([1.0, 0.0])

    result = detect_dry_equilibrium(mesh, minimum_saturated_thickness_m=0.0)

    assert result.detected is True
    np.testing.assert_allclose(result.internal_edge_flux_m3_s, [0.0])
    assert result.projected_residual_inf == pytest.approx(0.0)


def test_sloping_bottom_with_floor() -> None:
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


def test_prescribed_head_refuses() -> None:
    mesh = _mesh([0.0])

    result = detect_dry_equilibrium(
        mesh,
        recharge_rate_m_s=0.0,
        prescribed_head_m_by_cell=np.asarray([1.0], dtype=float),
    )

    assert result.detected is False
    assert result.positive_forcing_detected is True
    assert result.rejected_reason == "prescribed head above bottom present"


def test_steady_vi_skips_petsc() -> None:
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


def test_steady_vi_with_recharge_calls_petsc(monkeypatch) -> None:
    mesh = _mesh([0.0])

    def fake_solver(**_kwargs):
        raise RuntimeError("SNESVI path called")

    monkeypatch.setattr(vi_runtime.vi, "solve_vi_obstacle_problem", fake_solver)

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

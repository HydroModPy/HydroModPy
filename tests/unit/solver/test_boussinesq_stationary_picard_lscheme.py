from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    SteadySolveInputs,
)
from hydromodpy.solver.boussinesq.runtimes.stationary_picard_lscheme import (
    PICARD_LSCHEME_FINAL_CELLS_CSV,
    PICARD_LSCHEME_ITERATIONS_CSV,
    PICARD_LSCHEME_SUMMARY_JSON,
    PICARD_VI_CYCLE_SUMMARY_JSON,
    PICARD_VI_CYCLES_CSV,
    PicardLschemeOptions,
    PicardViCycleOptions,
    _assemble_strict_steady_residual,
    bounded_picard_lscheme,
    bounded_picard_vi_cycles,
)
from tests._helpers.mesh_doubles import _MiniMesh, line_mesh


def _mesh(z_bottom: list[float], *, k_m_s: float = 1.0e-5) -> _MiniMesh:
    return line_mesh(z_bottom, k_m_s=k_m_s, storage_coefficient=0.10)


def _options(**overrides) -> NonlinearRuntimeOptions:
    payload = {
        "regularization_radius": 0.05,
        "max_iterations": 20,
        "tol_residual_inf": 1.0e-10,
        "tol_state_update_inf": 1.0e-10,
    }
    payload.update(overrides)
    return NonlinearRuntimeOptions(**payload)


def test_picard_options_construct_strict_defaults() -> None:
    options = PicardLschemeOptions()

    assert options.picard_max_iterations == 500
    assert options.picard_lscheme_L == "auto"
    assert options.picard_final_vi_check is False
    assert not hasattr(options, "picard_b_min")
    assert not hasattr(options, "picard_drainage_mode")


def test_picard_vi_cycle_options_construct() -> None:
    options = PicardViCycleOptions()

    assert options.cycle_max == 10
    assert options.picard_steps_per_cycle == 200
    assert options.vi_max_iterations_per_cycle == 20
    assert options.picard_options.picard_relaxation_omega == pytest.approx(1.0)
    assert options.picard_options.picard_output_diagnostics is False


def test_single_cell_zero_recharge_stays_admissible_and_writes_diagnostics(
    tmp_path: Path,
) -> None:
    mesh = _mesh([0.0])

    result = bounded_picard_lscheme(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.asarray([0.0], dtype=float),
            recharge_rate_m_s=0.0,
            options=_options(tol_residual_inf=1.0e-12),
        ),
        picard_options=PicardLschemeOptions(
            picard_max_iterations=5,
            picard_tolerance_residual_inf=1.0e-12,
        ),
        diagnostics_dir=tmp_path,
        case_id="single_cell",
    )

    assert result.converged is True
    assert np.all(np.isfinite(result.head_m))
    np.testing.assert_allclose(result.head_m, mesh.z_bottom_m)
    assert result.diagnostics is not None
    assert result.diagnostics["strict_problem_definition"] is True
    json.dumps(result.diagnostics)
    assert (tmp_path / PICARD_LSCHEME_SUMMARY_JSON).exists()
    assert (tmp_path / PICARD_LSCHEME_ITERATIONS_CSV).exists()
    assert (tmp_path / PICARD_LSCHEME_FINAL_CELLS_CSV).exists()


def test_two_cell_strict_bottom_has_no_flux_on_flat_bottom() -> None:
    mesh = _mesh([0.0, 0.0])

    assembly = _assemble_strict_steady_residual(
        mesh,
        mesh.z_bottom_m,
        recharge_rate_m_s=0.0,
    )

    np.testing.assert_allclose(assembly.internal_edge_flux_m3_s, [0.0])
    np.testing.assert_allclose(assembly.saturated_thickness_m, [0.0, 0.0])
    np.testing.assert_allclose(assembly.transmissivity_m2_s, [0.0, 0.0])


def test_two_cell_strict_sloping_bottom_has_no_artificial_film_flux() -> None:
    mesh = _mesh([1.0, 0.0])

    assembly = _assemble_strict_steady_residual(
        mesh,
        mesh.z_bottom_m,
        recharge_rate_m_s=0.0,
    )

    np.testing.assert_allclose(assembly.saturated_thickness_m, [0.0, 0.0])
    np.testing.assert_allclose(assembly.internal_edge_flux_m3_s, [0.0])
    np.testing.assert_allclose(assembly.flow_residual_m3_s, [0.0, 0.0])


def test_hillslope_drain_zero_produces_admissible_initial_guess() -> None:
    mesh = _mesh([2.0, 1.0, 0.0])

    result = bounded_picard_lscheme(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=mesh.z_bottom_m.copy(),
            recharge_rate_m_s=0.0,
            drainage_conductance_m2_s=0.0,
            options=_options(),
        ),
        picard_options=PicardLschemeOptions(
            picard_max_iterations=12,
            picard_tolerance_residual_inf=1.0e-12,
            picard_usable_residual_inf=1.0,
        ),
    )

    assert np.min(result.head_m - mesh.z_bottom_m) >= -1.0e-12
    assert np.max(result.head_m - mesh.z_top_m) <= 1.0e-12
    assert np.all(result.assembly.saturated_thickness_m >= -1.0e-12)
    assert np.all(np.isfinite(result.head_m))


def test_strict_single_cell_recharge_balances_on_top_obstacle() -> None:
    mesh = _mesh([0.0])

    result = bounded_picard_lscheme(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.asarray([0.0], dtype=float),
            recharge_rate_m_s=1.0e-8,
            options=_options(tol_residual_inf=1.0e-12),
        ),
        picard_options=PicardLschemeOptions(
            picard_max_iterations=3,
            picard_tolerance_residual_inf=1.0e-12,
            picard_usable_residual_inf=1.0e-6,
        ),
    )

    assert result.converged is True
    assert result.diagnostics is not None
    assert result.diagnostics["active_top_count"] == 1
    np.testing.assert_allclose(result.head_m, mesh.z_top_m)
    np.testing.assert_allclose(result.assembly.saturation_excess_rate_m_s, [1.0e-8])


@pytest.mark.petsc
def test_picard_then_strict_vi_converges_on_prescribed_single_cell() -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")
    mesh = _mesh([0.0])

    result = bounded_picard_lscheme(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.asarray([0.0], dtype=float),
            recharge_rate_m_s=0.0,
            prescribed_head_m_by_cell=np.asarray([0.5], dtype=float),
            options=_options(tol_residual_inf=1.0e-12),
        ),
        picard_options=PicardLschemeOptions(
            picard_max_iterations=5,
            picard_tolerance_residual_inf=1.0e-12,
            picard_final_vi_check=True,
        ),
    )

    assert result.converged is True
    assert result.diagnostics is not None
    assert result.diagnostics["final_vi_converged"] is True
    np.testing.assert_allclose(result.head_m, [0.5], atol=1.0e-12)


@pytest.mark.petsc
def test_picard_vi_cycles_converges_on_prescribed_single_cell(tmp_path: Path) -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")
    mesh = _mesh([0.0])

    result = bounded_picard_vi_cycles(
        SteadySolveInputs(
            mesh=mesh,
            head_initial_guess_m=np.asarray([0.0], dtype=float),
            recharge_rate_m_s=0.0,
            prescribed_head_m_by_cell=np.asarray([0.5], dtype=float),
            options=_options(tol_residual_inf=1.0e-12),
        ),
        cycle_options=PicardViCycleOptions(
            cycle_max=2,
            picard_steps_per_cycle=2,
            vi_max_iterations_per_cycle=5,
        ),
        diagnostics_dir=tmp_path,
        case_id="prescribed_single_cell_cycles",
    )

    assert result.converged is True
    assert result.diagnostics is not None
    assert result.diagnostics["method"] == "bounded_picard_vi_cycles"
    assert result.diagnostics["final_vi_converged"] is True
    np.testing.assert_allclose(result.head_m, [0.5], atol=1.0e-12)
    assert (tmp_path / PICARD_VI_CYCLE_SUMMARY_JSON).exists()
    assert (tmp_path / PICARD_VI_CYCLES_CSV).exists()
    assert (tmp_path / PICARD_LSCHEME_FINAL_CELLS_CSV).exists()

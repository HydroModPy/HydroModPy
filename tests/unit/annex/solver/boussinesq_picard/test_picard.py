"""Bounded Picard solver of the steady Boussinesq problem (heads and thicknesses in m).

The strict residual gives no film flux over a dry bottom, and an imposed head
takes no recharge, well or drain, as in MODFLOW. Cases are one to three cells.
"""

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
from hydromodpy_annex.solver.boussinesq_picard.diagnostics import (
    PicardLschemeOptions,
    PicardViCycleOptions,
)
from hydromodpy_annex.solver.boussinesq_picard.io import (
    PICARD_LSCHEME_FINAL_CELLS_CSV,
    PICARD_LSCHEME_ITERATIONS_CSV,
    PICARD_LSCHEME_SUMMARY_JSON,
    PICARD_VI_CYCLE_SUMMARY_JSON,
    PICARD_VI_CYCLES_CSV,
)
from hydromodpy_annex.solver.boussinesq_picard.lscheme import bounded_picard_lscheme
from hydromodpy_annex.solver.boussinesq_picard.picard import (
    assemble_strict_steady_residual,
    bounded_picard_vi_cycles,
)
from tests._helpers.boussinesq_mesh_doubles import _MiniMesh, line_mesh

RECHARGE_M_S = 5.0e-3 / 86400.0
WELL_M3_S = -2.0e-4
DRAIN_M2_S = 1.0e-3


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


def test_lscheme_defaults() -> None:
    options = PicardLschemeOptions()

    assert options.picard_max_iterations == 500
    assert options.picard_lscheme_L == "auto"
    assert options.picard_final_vi_check is False
    assert not hasattr(options, "picard_b_min")
    assert not hasattr(options, "picard_drainage_mode")


def test_vi_cycle_defaults() -> None:
    options = PicardViCycleOptions()

    assert options.cycle_max == 10
    assert options.picard_steps_per_cycle == 200
    assert options.vi_max_iterations_per_cycle == 20
    assert options.picard_options.picard_relaxation_omega == pytest.approx(1.0)
    assert options.picard_options.picard_output_diagnostics is False


def test_dry_cell_writes_diagnostics(
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


DRY_BOTTOMS = [
    pytest.param([0.0, 0.0], id="flat bottom"),
    pytest.param([1.0, 0.0], id="sloping bottom"),
]


@pytest.mark.parametrize("z_bottom", DRY_BOTTOMS)
def test_dry_two_cells_have_no_flux(z_bottom) -> None:
    # Heads at the bottom leave no saturated thickness, so no film flux either.
    mesh = _mesh(z_bottom)

    assembly = assemble_strict_steady_residual(mesh, mesh.z_bottom_m, recharge_rate_m_s=0.0)

    np.testing.assert_allclose(assembly.saturated_thickness_m, [0.0, 0.0])
    np.testing.assert_allclose(assembly.transmissivity_m2_s, [0.0, 0.0])
    np.testing.assert_allclose(assembly.internal_edge_flux_m3_s, [0.0])
    np.testing.assert_allclose(assembly.flow_residual_m3_s, [0.0, 0.0])


def test_recharge_on_top_obstacle() -> None:
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
def test_final_vi_check_on_imposed_head() -> None:
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
def test_vi_cycles_on_imposed_head(tmp_path: Path) -> None:
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


def _strip(n_cells: int, *, outlet_top_m: float = 50.0) -> _MiniMesh:
    """Return a row of 10 m square cells, 50 m thick, joined by their sides."""
    n_edges = n_cells - 1
    z_top = np.full(n_cells, 50.0)
    z_top[0] = outlet_top_m
    return _MiniMesh(
        cell_area_m2=np.full(n_cells, 100.0),
        z_top_m=z_top,
        z_bottom_m=np.zeros(n_cells),
        hydraulic_conductivity_m_s=np.full(n_cells, 1.0e-4),
        storage_coefficient=np.full(n_cells, 0.1),
        edge_ids=np.arange(n_edges),
        edge_cell_a=np.arange(n_edges),
        edge_cell_b=np.arange(1, n_cells),
        edge_length_m=np.full(n_edges, 10.0),
        edge_distance_m=np.full(n_edges, 10.0),
        edge_midpoint_distance_to_cell_a_m=np.full(n_edges, 5.0),
        edge_midpoint_distance_to_cell_b_m=np.full(n_edges, 5.0),
    )


def test_imposed_head_cell_takes_no_source() -> None:
    # The held head stands 1 m above the ground of its cell, under a well.
    mesh = _strip(3, outlet_top_m=19.0)
    head = np.asarray([20.0, 21.0, 21.5])
    prescribed = np.full(3, np.nan)
    prescribed[0] = 20.0
    wells = np.asarray([WELL_M3_S, 0.0, WELL_M3_S])

    assembly = assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=RECHARGE_M_S,
        well_flux_m3_s=wells,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=DRAIN_M2_S,
    )

    np.testing.assert_allclose(assembly.recharge_rate_m_s, [0.0, RECHARGE_M_S, RECHARGE_M_S])
    np.testing.assert_allclose(assembly.well_flux_m3_s, [0.0, 0.0, WELL_M3_S])
    np.testing.assert_allclose(assembly.drainage_flux_m3_s, 0.0)
    assert assembly.prescribed_head_flux_m3_s[0] == pytest.approx(
        -assembly.internal_edge_flux_m3_s[0]
    )

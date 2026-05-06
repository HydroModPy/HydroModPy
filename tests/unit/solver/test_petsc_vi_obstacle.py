from __future__ import annotations

import csv
import json
import platform
from dataclasses import dataclass

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.assembly import BoussinesqAssembly
from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    RuntimeSolveResult,
    TransientStepInputs,
)
import hydromodpy.solver.boussinesq.runtimes.petsc_vi_obstacle as vi_runtime
from hydromodpy.solver.boussinesq.runtimes.petsc_vi_obstacle import (
    _projected_vi_residual,
    solve_transient_step,
)
from hydromodpy.solver.boussinesq.runtimes.vi_obstacle_diagnostics import (
    VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
    VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
    VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV,
    build_vi_obstacle_runtime_summary,
    write_vi_obstacle_diagnostic_files,
)


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


def _assembly(mesh: _MiniMesh, head_m: np.ndarray) -> BoussinesqAssembly:
    zeros_cells = np.zeros(mesh.n_cells, dtype=float)
    return BoussinesqAssembly(
        head_m=np.asarray(head_m, dtype=float).copy(),
        saturated_thickness_m=zeros_cells.copy(),
        transmissivity_m2_s=zeros_cells.copy(),
        recharge_rate_m_s=zeros_cells.copy(),
        well_flux_m3_s=zeros_cells.copy(),
        saturation_excess_rate_m_s=zeros_cells.copy(),
        internal_edge_flux_m3_s=np.zeros(mesh.n_edges, dtype=float),
        prescribed_head_flux_m3_s=zeros_cells.copy(),
        prescribed_head_m_by_cell=np.full(mesh.n_cells, np.nan, dtype=float),
        head_constraint_residual_m=zeros_cells.copy(),
        boundary_edge_flux_m3_s=np.zeros(mesh.n_edges, dtype=float),
        drainage_flux_m3_s=zeros_cells.copy(),
        flow_residual_m3_s=zeros_cells.copy(),
        solver_residual=zeros_cells.copy(),
        residual_m3_s=zeros_cells.copy(),
        dry_deficit_rate_m_s=zeros_cells.copy(),
    )


def test_projected_vi_residual_uses_petsc_bound_sign_convention() -> None:
    projected = _projected_vi_residual(
        residual=np.asarray([1.0, -2.0, -3.0, 4.0], dtype=float),
        head_m=np.asarray([0.0, 0.0, 1.0, 1.0], dtype=float),
        lower_m=np.zeros(4, dtype=float),
        upper_m=np.ones(4, dtype=float),
        prescribed_mask=np.zeros(4, dtype=bool),
        tol_h=1.0e-12,
    )

    np.testing.assert_allclose(projected, np.asarray([0.0, -2.0, 0.0, 4.0]))


@pytest.mark.petsc
def test_single_cell_recharge_activates_upper_obstacle_reaction() -> None:
    _require_linux_petsc4py()
    mesh = _single_cell_mesh()

    result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray([1.9], dtype=float),
            dt_seconds=10.0,
            head_initial_guess_m=np.asarray([1.9], dtype=float),
            recharge_rate_m_s=0.01,
            well_flux_m3_s=np.asarray([0.0], dtype=float),
            options=NonlinearRuntimeOptions(
                regularization_radius=0.05,
                max_iterations=20,
                tol_residual_inf=1.0e-12,
            ),
        )
    )

    assert result.converged is True
    assert result.residual_norm_inf <= 1.0e-12
    np.testing.assert_allclose(result.head_m, mesh.z_top_m, atol=1.0e-12)
    assert float(result.assembly.saturation_excess_rate_m_s[0]) > 0.0
    assert float(result.assembly.dry_deficit_rate_m_s[0]) == pytest.approx(0.0)
    assert float(result.head_m[0]) <= float(mesh.z_top_m[0]) + 1.0e-12
    assert result.diagnostics is not None
    assert int(result.diagnostics["surface_active_cells"]) == 1
    assert int(result.diagnostics["vi_substeps_requested"]) == 1
    assert int(result.diagnostics["vi_substeps_used"]) == 1
    assert float(result.diagnostics["surface_reaction_total_m3_s"]) > 0.0
    assert float(result.diagnostics["surface_reaction_wrong_sign_m3_s"]) == pytest.approx(0.0)


@pytest.mark.petsc
def test_single_cell_pumping_activates_lower_obstacle_reaction() -> None:
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
                max_iterations=20,
                tol_residual_inf=1.0e-12,
            ),
        )
    )

    assert result.converged is True
    assert result.residual_norm_inf <= 1.0e-12
    np.testing.assert_allclose(result.head_m, mesh.z_bottom_m, atol=1.0e-12)
    assert float(result.assembly.saturation_excess_rate_m_s[0]) == pytest.approx(0.0)
    assert float(result.assembly.dry_deficit_rate_m_s[0]) > 0.0
    assert float(result.head_m[0]) >= float(mesh.z_bottom_m[0]) - 1.0e-12
    assert result.diagnostics is not None
    assert int(result.diagnostics["bottom_active_cells"]) == 1
    assert float(result.diagnostics["bottom_reaction_total_m3_s"]) > 0.0
    assert float(result.diagnostics["bottom_reaction_wrong_sign_m3_s"]) == pytest.approx(0.0)


@pytest.mark.petsc
def test_single_cell_recharge_uses_requested_vi_substeps(tmp_path) -> None:
    _require_linux_petsc4py()
    mesh = _single_cell_mesh()

    result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray([1.9], dtype=float),
            dt_seconds=10.0,
            head_initial_guess_m=np.asarray([1.9], dtype=float),
            recharge_rate_m_s=0.01,
            well_flux_m3_s=np.asarray([0.0], dtype=float),
            options=NonlinearRuntimeOptions(
                regularization_radius=0.05,
                max_iterations=20,
                tol_residual_inf=1.0e-12,
                vi_substeps_per_period=2,
            ),
        )
    )

    assert result.converged is True
    np.testing.assert_allclose(result.head_m, mesh.z_top_m, atol=1.0e-12)
    assert result.diagnostics is not None
    assert int(result.diagnostics["vi_substeps_requested"]) == 2
    assert int(result.diagnostics["vi_substeps_used"]) == 2
    assert result.diagnostics["vi_substep_attempts"] == [2]
    assert result.diagnostics["vi_substep_success"] is True
    assert result.diagnostics["vi_substep_rate_forcing_rescaled"] is False
    assert len(result.diagnostics["vi_substep_details"]) == 2
    assert all(
        item["dt_sub_seconds"] == pytest.approx(5.0)
        for item in result.diagnostics["vi_substep_details"]
    )
    assert result.iterations == int(result.diagnostics["vi_substep_total_snes_iterations"])
    assert np.min(result.head_m - mesh.z_bottom_m) >= -1.0e-12
    assert np.max(result.head_m - mesh.z_top_m) <= 1.0e-12
    assert np.min(result.assembly.saturation_excess_rate_m_s) >= -1.0e-12
    assert np.min(result.assembly.dry_deficit_rate_m_s) >= -1.0e-12

    runtime_summary = {
        "runtime_backend": "petsc",
        "runtime_engine": "petsc",
        "runtime_engine_id": "petsc_vi_obstacle_snes",
        "runtime_formulation": "head_only_vi_obstacle",
        "surface_interaction_model_resolved": "vi_obstacle",
        "vi_substeps_per_period": 2,
        "vi_substep_on_failure": False,
        "vi_max_adaptive_substeps": 2,
        "n_periods": 1,
        "period_lengths_seconds": [10.0],
        "converged_by_period": [True],
        "runtime_period_diagnostics": [{**result.diagnostics, "period_index": 0}],
        "runtime_substep_diagnostics": [
            {**item, "period_index": 0}
            for item in result.diagnostics["vi_substep_details"]
        ],
    }
    compact = build_vi_obstacle_runtime_summary(runtime_summary)
    json.dumps(compact)
    assert compact["vi_substeps_per_period"] == 2
    assert compact["max_substeps_used"] == 2
    assert compact["all_periods_converged"] is True

    paths = write_vi_obstacle_diagnostic_files(tmp_path, runtime_summary)
    assert set(paths) == {
        "runtime_summary",
        "period_diagnostics",
        "substep_diagnostics",
    }
    runtime_payload = json.loads((tmp_path / VI_OBSTACLE_RUNTIME_SUMMARY_JSON).read_text())
    assert runtime_payload["substep_diagnostic_count"] == 2
    with (tmp_path / VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV).open(newline="") as handle:
        period_rows = list(csv.DictReader(handle))
    with (tmp_path / VI_OBSTACLE_SUBSTEP_DIAGNOSTICS_CSV).open(newline="") as handle:
        substep_rows = list(csv.DictReader(handle))
    assert period_rows[0]["substeps_requested"] == "2"
    assert len(substep_rows) == 2
    assert substep_rows[0]["n_substeps_attempted"] == "2"


def test_adaptive_vi_substeps_restore_period_start_before_retry(monkeypatch) -> None:
    mesh = _single_cell_mesh()
    calls: list[np.ndarray] = []

    def fake_substep(**kwargs) -> RuntimeSolveResult:
        head_prev = np.asarray(kwargs["head_prev_m"], dtype=float).copy()
        calls.append(head_prev)
        call_index = len(calls)
        converged = call_index > 1
        head = head_prev + 0.25
        diagnostics = {
            "snes_converged_reason": 2 if converged else -6,
            "snes_converged_reason_label": (
                "SNES_CONVERGED_FNORM_ABS" if converged else "SNES_DIVERGED_LINE_SEARCH"
            ),
            "ksp_converged_reason": 2,
            "ksp_converged_reason_label": "KSP_CONVERGED_RTOL_NORMAL",
            "snes_iterations": 1,
            "ksp_iterations": 1,
            "max_violation_lower_m": 0.0,
            "max_violation_upper_m": 0.0,
            "surface_active_cells": 0,
            "bottom_active_cells": 0,
            "free_cells": mesh.n_cells,
            "surface_reaction_total_m3_s": 0.0,
            "bottom_reaction_total_m3_s": 0.0,
            "surface_reaction_total_m3": 0.0,
            "bottom_reaction_total_m3": 0.0,
            "free_residual_norm_inf": 0.0,
            "projected_vi_residual_norm_inf": 0.0,
        }
        return RuntimeSolveResult(
            head_m=head,
            assembly=_assembly(mesh, head),
            converged=converged,
            iterations=1,
            residual_norm_inf=0.0 if converged else 1.0,
            backend_name="petsc",
            termination_reason="fake converged" if converged else "fake failed",
            diagnostics=diagnostics,
        )

    monkeypatch.setattr(vi_runtime, "_solve_transient_vi_substep", fake_substep)

    result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray([1.0], dtype=float),
            dt_seconds=10.0,
            head_initial_guess_m=np.asarray([1.0], dtype=float),
            recharge_rate_m_s=0.0,
            well_flux_m3_s=np.asarray([0.0], dtype=float),
            options=NonlinearRuntimeOptions(
                regularization_radius=0.05,
                max_iterations=20,
                tol_residual_inf=1.0e-12,
                vi_substeps_per_period=1,
                vi_substep_on_failure=True,
                vi_max_adaptive_substeps=2,
            ),
        )
    )

    assert result.converged is True
    assert len(calls) == 3
    np.testing.assert_allclose(calls[0], np.asarray([1.0]))
    np.testing.assert_allclose(calls[1], np.asarray([1.0]))
    assert result.diagnostics is not None
    assert result.diagnostics["vi_substep_attempts"] == [1, 2]
    assert result.diagnostics["vi_substep_adaptive_used"] is True
    assert int(result.diagnostics["vi_substeps_used"]) == 2

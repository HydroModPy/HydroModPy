from __future__ import annotations

import csv
import json
import platform
from dataclasses import dataclass

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.runtime_contract import (
    NonlinearRuntimeOptions,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtimes import petsc_vi_obstacle
from hydromodpy.solver.boussinesq.runtimes.petsc_ts_vi_obstacle import (
    solve_transient_step,
)
from hydromodpy.solver.boussinesq.runtimes.ts_vi_obstacle_diagnostics import (
    TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV,
    TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON,
    TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV,
    build_ts_vi_obstacle_runtime_summary,
    write_ts_vi_obstacle_diagnostic_files,
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


def _options(**overrides) -> NonlinearRuntimeOptions:
    payload = {
        "regularization_radius": 0.05,
        "max_iterations": 20,
        "tol_residual_inf": 1.0e-12,
        "ts_vi_steps_per_period": 4,
        "ts_vi_adapt": False,
    }
    payload.update(overrides)
    return NonlinearRuntimeOptions(**payload)


@pytest.mark.petsc
def test_ts_vi_single_cell_recharge_activates_upper_obstacle_reaction(tmp_path) -> None:
    _require_linux_petsc4py()
    mesh = _single_cell_mesh()

    result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray([1.9], dtype=float),
            dt_seconds=10.0,
            recharge_rate_m_s=0.01,
            well_flux_m3_s=np.asarray([0.0], dtype=float),
            options=_options(),
        )
    )

    assert result.converged is True
    np.testing.assert_allclose(result.head_m, mesh.z_top_m, atol=1.0e-12)
    assert float(result.head_m[0]) <= float(mesh.z_top_m[0]) + 1.0e-12
    assert float(result.assembly.saturation_excess_rate_m_s[0]) > 0.0
    assert float(result.assembly.dry_deficit_rate_m_s[0]) == pytest.approx(0.0)
    assert result.diagnostics is not None
    assert int(result.diagnostics["ts_steps_taken"]) == 4
    assert len(result.diagnostics["ts_vi_step_details"]) == 4
    assert int(result.diagnostics["surface_active_cells"]) == 1
    assert float(result.diagnostics["surface_reaction_total_m3_s"]) > 0.0
    assert float(result.diagnostics["max_violation_upper_m"]) == pytest.approx(0.0)

    runtime_summary = {
        "runtime_backend": "petsc",
        "runtime_engine": "petsc",
        "runtime_engine_id": "petsc_ts_vi_obstacle",
        "runtime_formulation": "head_only_ts_vi_obstacle",
        "surface_interaction_model_resolved": "ts_vi_obstacle",
        "ts_vi_steps_per_period": 4,
        "ts_vi_adapt": False,
        "n_periods": 1,
        "period_lengths_seconds": [10.0],
        "converged_by_period": [True],
        "runtime_period_diagnostics": [{**result.diagnostics, "period_index": 0}],
        "runtime_ts_step_diagnostics": [
            {**item, "period_index": 0}
            for item in result.diagnostics["ts_vi_step_details"]
        ],
    }
    compact = build_ts_vi_obstacle_runtime_summary(runtime_summary)
    json.dumps(compact)
    assert compact["total_ts_steps"] == 4
    assert compact["all_periods_converged"] is True

    paths = write_ts_vi_obstacle_diagnostic_files(tmp_path, runtime_summary)
    assert set(paths) == {
        "runtime_summary",
        "period_diagnostics",
        "step_diagnostics",
    }
    runtime_payload = json.loads((tmp_path / TS_VI_OBSTACLE_RUNTIME_SUMMARY_JSON).read_text())
    assert runtime_payload["step_diagnostic_count"] == 4
    with (tmp_path / TS_VI_OBSTACLE_PERIOD_DIAGNOSTICS_CSV).open(newline="") as handle:
        period_rows = list(csv.DictReader(handle))
    with (tmp_path / TS_VI_OBSTACLE_STEP_DIAGNOSTICS_CSV).open(newline="") as handle:
        step_rows = list(csv.DictReader(handle))
    assert period_rows[0]["ts_steps_taken"] == "4"
    assert len(step_rows) == 4


@pytest.mark.petsc
def test_ts_vi_single_cell_pumping_activates_lower_obstacle_reaction() -> None:
    _require_linux_petsc4py()
    mesh = _single_cell_mesh()

    result = solve_transient_step(
        TransientStepInputs(
            mesh=mesh,
            head_prev_m=np.asarray([0.1], dtype=float),
            dt_seconds=10.0,
            recharge_rate_m_s=0.0,
            well_flux_m3_s=np.asarray([-0.01], dtype=float),
            options=_options(),
        )
    )

    assert result.converged is True
    np.testing.assert_allclose(result.head_m, mesh.z_bottom_m, atol=1.0e-12)
    assert float(result.head_m[0]) >= float(mesh.z_bottom_m[0]) - 1.0e-12
    assert float(result.assembly.saturation_excess_rate_m_s[0]) == pytest.approx(0.0)
    assert float(result.assembly.dry_deficit_rate_m_s[0]) > 0.0
    assert result.diagnostics is not None
    assert int(result.diagnostics["bottom_active_cells"]) == 1
    assert float(result.diagnostics["bottom_reaction_total_m3_s"]) > 0.0
    assert float(result.diagnostics["max_violation_lower_m"]) == pytest.approx(0.0)


@pytest.mark.petsc
def test_ts_vi_matches_manual_vi_substeps_on_single_cell() -> None:
    _require_linux_petsc4py()
    mesh = _single_cell_mesh()
    common = dict(
        mesh=mesh,
        head_prev_m=np.asarray([1.0], dtype=float),
        dt_seconds=10.0,
        recharge_rate_m_s=0.005,
        well_flux_m3_s=np.asarray([0.0], dtype=float),
    )

    manual = petsc_vi_obstacle.solve_transient_step(
        TransientStepInputs(
            **common,
            options=_options(vi_substeps_per_period=4),
        )
    )
    ts_result = solve_transient_step(
        TransientStepInputs(
            **common,
            options=_options(ts_vi_steps_per_period=4),
        )
    )

    assert manual.converged is True
    assert ts_result.converged is True
    np.testing.assert_allclose(ts_result.head_m, manual.head_m, atol=1.0e-10)
    assert ts_result.diagnostics is not None
    assert int(ts_result.diagnostics["ts_steps_taken"]) == 4
    assert int(ts_result.diagnostics["surface_active_cells"]) == int(
        manual.diagnostics["surface_active_cells"]
    )

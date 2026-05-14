from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hydromodpy.solver.boussinesq.runtime_contract import NonlinearRuntimeOptions


def _load_script_module():
    path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "projects"
        / "10_testbed_workflow"
        / "boussinesq"
        / "natural_geology_k"
        / "run_bouss_stationary_robust_solver_matrix.py"
    )
    spec = importlib.util.spec_from_file_location("robust_solver_matrix", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
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


def _single_cell_loaded(module):
    mesh = _MiniMesh(
        cell_area_m2=np.asarray([10.0], dtype=float),
        z_top_m=np.asarray([2.0], dtype=float),
        z_bottom_m=np.asarray([0.0], dtype=float),
        hydraulic_conductivity_m_s=np.asarray([1.0e-5], dtype=float),
        storage_coefficient=np.asarray([0.05], dtype=float),
        edge_ids=np.asarray([], dtype=int),
        edge_cell_a=np.asarray([], dtype=int),
        edge_cell_b=np.asarray([], dtype=int),
        edge_length_m=np.asarray([], dtype=float),
        edge_distance_m=np.asarray([], dtype=float),
        edge_midpoint_distance_to_cell_a_m=np.asarray([], dtype=float),
        edge_midpoint_distance_to_cell_b_m=np.asarray([], dtype=float),
    )
    return module.baseline.LoadedCase(
        spec=module.baseline.CaseSpec(
            case_id="mini",
            source_config=Path("mini.toml"),
            known_status="unit test",
        ),
        mesh=mesh,
        recharge_rate_m_s=0.0,
        drainage_conductance_m2_s=0.0,
        k_value_m_s=1.0e-5,
        sy_value=0.05,
        options=NonlinearRuntimeOptions(
            regularization_radius=0.05,
            max_iterations=10,
            tol_residual_inf=1.0e-10,
            tol_state_update_inf=1.0e-10,
        ),
    )


def test_bmin_and_smooth_schedules_end_on_target_model() -> None:
    module = _load_script_module()

    assert module.bmin_schedule()[0] > module.bmin_schedule()[-1]
    assert module.bmin_schedule()[-1] == 0.0
    assert module.smooth_eps_schedule()[0] > module.smooth_eps_schedule()[-1]
    assert module.smooth_eps_schedule()[-1] == 0.0


def test_smoothplus_is_positive_and_has_bounded_derivative() -> None:
    module = _load_script_module()
    values = np.asarray([-10.0, 0.0, 10.0], dtype=float)

    smooth = module._smoothplus(values, 0.5)
    derivative = module._smoothplus_derivative(values, 0.5)

    assert np.all(smooth >= 0.0)
    assert smooth[0] < 0.02
    assert smooth[-1] > 9.99
    assert np.all(derivative >= 0.0)
    assert np.all(derivative <= 1.0)


def test_picard_lscheme_converges_on_single_cell_zero_forcing() -> None:
    module = _load_script_module()
    loaded = _single_cell_loaded(module)

    result, stages = module._solve_picard_lscheme(
        loaded=loaded,
        head_initial_guess_m=np.asarray([1.0], dtype=float),
        b_min_m=0.0,
        smooth_eps_m=0.0,
        max_iterations=5,
        omega=1.0,
        lscheme_l=1.0e-6,
    )

    assert result.converged is True
    assert result.residual_norm_inf <= 1.0e-10
    assert stages

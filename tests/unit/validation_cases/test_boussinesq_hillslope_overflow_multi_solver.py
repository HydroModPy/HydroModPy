from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_multi_solver_case import (
    DEFAULT_SOLVERS,
    TimedSolverDiagnostics,
    _align_recharge_series_to_elapsed,
    _build_execution_rows,
    _build_timeseries_rows,
    _normalize_solver_names,
)
from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.runtime_boussinesq import (
    WINDOWS_SURFACE_CONTEXT_PRESET,
    _resolve_case_settings,
    resolve_solver_variant,
)


def _make_result(*, solver_name: str, solver_label: str) -> TimedSolverDiagnostics:
    diagnostics = SimpleNamespace(
        solver_name=solver_name,
        solver_label=solver_label,
        runtime_backend="petsc" if "petsc" in solver_name else "local",
        surface_interaction_model=(
            "complementarity" if solver_name == "petsc" else "regularized_partition"
        ),
        elapsed_days=np.asarray([0.0, 2.0], dtype=float),
        recharge_mm_day=np.asarray([0.0, 6.0], dtype=float),
        recharge_flux_m3_day=np.asarray([0.0, 12.0], dtype=float),
        surface_excess_flux_m3_day=np.asarray([0.1, 0.2], dtype=float),
        east_boundary_outflow_m3_day=np.asarray([0.05, 0.15], dtype=float),
        total_outflow_m3_day=np.asarray([0.15, 0.35], dtype=float),
        storage_balance_m3_day=np.asarray([-0.15, 11.65], dtype=float),
        total_overflow_m3_day=np.asarray([0.1, 0.2], dtype=float),
        active_overflow_length_m=np.asarray([0.0, 10.0], dtype=float),
        overflow_front_x_m=np.asarray([np.nan, 100.0], dtype=float),
        overflow_centroid_x_m=np.asarray([np.nan, 80.0], dtype=float),
        x_m=np.asarray([10.0, 20.0], dtype=float),
        topography_profile_m=np.asarray([5.0, 4.0], dtype=float),
        mean_head_profiles_m=np.asarray([[5.1, 4.1], [5.2, 4.3]], dtype=float),
        mean_head_clearance_m=np.asarray([[0.0, 0.1], [0.2, 0.3]], dtype=float),
        result=SimpleNamespace(out_path=Path("dummy")),
        onset_day=2.0,
        peak_total_overflow_m3_day=0.2,
        peak_overflow_day=2.0,
        max_head_clearance_m=0.3,
    )
    return TimedSolverDiagnostics(diagnostics=diagnostics, wall_time_seconds=1.23)


def test_normalize_solver_names_defaults_and_removes_duplicates() -> None:
    assert _normalize_solver_names(None) == DEFAULT_SOLVERS
    assert _normalize_solver_names(["boussinesq", "petsc", "boussinesq"]) == (
        "boussinesq",
        "petsc",
    )


def test_build_rows_export_expected_fields() -> None:
    results = [_make_result(solver_name="petsc", solver_label="PETSc complementarity")]
    timeseries_rows = _build_timeseries_rows(results)
    execution_rows = _build_execution_rows(results)

    assert len(timeseries_rows) == 2
    assert timeseries_rows[1]["solver"] == "petsc"
    assert timeseries_rows[1]["total_overflow_m3_day"] == 0.2
    assert timeseries_rows[1]["total_outflow_m3_day"] == 0.35
    assert timeseries_rows[1]["surface_excess_flux_m3_day"] == 0.2
    assert timeseries_rows[1]["max_head_clearance_m"] == 0.3

    assert execution_rows == [
        {
            "solver": "petsc",
            "solver_label": "PETSc complementarity",
            "runtime_backend": "petsc",
            "surface_interaction_model": "complementarity",
            "wall_time_seconds": 1.23,
            "results_dir": "dummy",
        }
    ]


def test_align_recharge_series_to_elapsed_pads_initial_state() -> None:
    aligned = _align_recharge_series_to_elapsed(
        np.asarray([6.0, 12.0], dtype=float),
        np.asarray([0.0, 2.0, 4.0], dtype=float),
    )
    np.testing.assert_allclose(aligned, np.asarray([6.0, 6.0, 12.0], dtype=float))


def test_windows_surface_context_preset_overrides_geometry_and_forcing() -> None:
    metadata = {
        "geometry": {
            "nx": 1,
            "ny": 1,
            "length_x_m": 1.0,
            "width_y_m": 1.0,
            "bottom_elevation_m": 0.0,
            "toe_elevation_m": 0.0,
            "topography_slope_m_per_m": 0.0,
            "east_head_m": 0.0,
            "initial_head_m": 0.0,
            "hydraulic_conductivity_m_per_s": 1.0,
            "storage_coefficient": 1.0,
        },
        "time": {"dt_days": 1.0},
        "forcing": {"first_clim": "first", "recharge_mm_day": [1.0]},
    }
    geometry_cfg, time_cfg, forcing_cfg, _, _ = _resolve_case_settings(
        metadata,
        variant=resolve_solver_variant("petsc_partition"),
        context_preset=WINDOWS_SURFACE_CONTEXT_PRESET,
        forcing_preset=None,
        forcing_scale=1.0,
        east_head_m=None,
        initial_head_m=None,
        dt_days=None,
        runtime_max_iterations=None,
        runtime_tol_residual_inf=None,
    )

    assert geometry_cfg["length_x_m"] == 400.0
    assert geometry_cfg["width_y_m"] == 30.0
    assert geometry_cfg["hydraulic_conductivity_m_per_s"] == 2.0e-5
    assert geometry_cfg["drainage_conductance_m2_s"] == 1.0e-4
    assert time_cfg["dt_days"] == 15.0
    assert forcing_cfg["recharge_mm_day"][-1] == 0.0
    assert len(forcing_cfg["recharge_mm_day"]) == 28

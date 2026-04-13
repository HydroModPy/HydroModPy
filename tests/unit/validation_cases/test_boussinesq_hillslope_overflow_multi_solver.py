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
        total_overflow_m3_day=np.asarray([0.1, 0.2], dtype=float),
        active_overflow_length_m=np.asarray([0.0, 10.0], dtype=float),
        overflow_front_x_m=np.asarray([np.nan, 100.0], dtype=float),
        overflow_centroid_x_m=np.asarray([np.nan, 80.0], dtype=float),
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

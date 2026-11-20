"""Validate the steady same-solver twin benchmark for calibration."""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    TwinCheck,
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_TWIN_CASE,
)

NOT_APPLICABLE = {
    "modflow_nwt": "The only observable is the east boundary flux, which is exactly proportional to K for fixed heads and no sources, so the normalized cost and the recovery do not depend on the solver. Measured on NWT, MF6 triangles and MF6 Voronoi: grid, random search, Optuna and CMA-ES return identical errors.",
    "modflow6_irregular_tri": "The only observable is the east boundary flux, which is exactly proportional to K for fixed heads and no sources, so the normalized cost and the recovery do not depend on the solver. Measured on NWT, MF6 triangles and MF6 Voronoi: grid, random search, Optuna and CMA-ES return identical errors.",
    "modflow6_voronoi": "The only observable is the east boundary flux, which is exactly proportional to K for fixed heads and no sources, so the normalized cost and the recovery do not depend on the solver. Measured on NWT, MF6 triangles and MF6 Voronoi: grid, random search, Optuna and CMA-ES return identical errors.",
    "boussinesq": "The only observable is the east boundary flux, which is exactly proportional to K for fixed heads and no sources, so the normalized cost and the recovery do not depend on the solver. The head stays far below the surface, so the Boussinesq obstacle closure never acts.",
    "boussinesq_local": "The only observable is the east boundary flux, which is exactly proportional to K for fixed heads and no sources, so the normalized cost and the recovery do not depend on the solver. The head stays far below the surface, so the surface closure never acts.",
}


def _assert_modflow6_runtime_available() -> None:
    """Require the MODFLOW 6 runtime used by the Dupuit twin benchmarks."""
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.mf6
@pytest.mark.xdist_group(name="twin_dupuit_steady")
def test_calibration_twin_dupuit_fixed_head_modflow6_benchmark_recovers_truth() -> None:
    """Run the steady twin benchmark and verify standardized methods recover the truth."""
    pytest.importorskip("optuna")
    pytest.importorskip("cma")

    _assert_modflow6_runtime_available()

    benchmark = run_lightweight_twin_benchmark_case(
        STEADY_DUPUIT_TWIN_CASE,
        caller_file=__file__,
        checks={
            "grid": TwinCheck(best_within=1.0),
            "random_search": TwinCheck(best_within=1.0, in_distribution=True),
            "optuna": TwinCheck(meets_target=True, in_distribution=True),
            "cma_es": TwinCheck(best_within=1.0),
            "scipy_nelder_mead": TwinCheck(best_within=1.0),
        },
    )

    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 6
    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.iteration_count >= 1
        assert result.n_evaluations >= 1
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_global" in result.param_abs_error
        assert_lightweight_method_result(result)
        if result.method_name in {"random_search", "optuna"}:
            assert result.model_distribution_sample_count >= 1


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.mf6
@pytest.mark.xdist_group(name="twin_dupuit_steady")
def test_calibration_twin_dupuit_fixed_head_modflow6_fast_grid_search_smoke() -> None:
    """Run one budget-capped smoke benchmark that stays genuinely quick."""
    _assert_modflow6_runtime_available()

    benchmark = run_lightweight_twin_benchmark_case(
        STEADY_DUPUIT_TWIN_CASE,
        caller_file=__file__,
        method_names=("grid",),
        evaluation_budget=6,
        checks={"grid": TwinCheck(best_within=1.0)},
    )

    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == 1
    result = benchmark.method_results[0]
    assert result.method_name == "grid"
    assert result.requested_evaluation_budget == 6
    assert result.n_evaluations == 6
    assert result.cost_best is not None
    assert math.isfinite(float(result.cost_best)), result.to_mapping()
    assert result.session_prepare_time_seconds is not None
    assert result.mean_candidate_total_time_seconds is not None
    assert result.mean_candidate_preparation_time_seconds is not None
    assert result.mean_candidate_simulation_time_seconds is not None
    assert "K_global" in result.param_abs_error
    assert_lightweight_method_result(result)

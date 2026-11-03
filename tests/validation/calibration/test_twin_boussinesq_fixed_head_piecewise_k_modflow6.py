"""Validation of zoned K recovery by calibration methods on a steady twin, per solver.

Compared with: the three zone conductivities that produced the observations.

A run with K = 2e-4, 5e-5 and 1e-4 m/s in three bands of a fixed-head strip gives three
heads and the east outlet discharge. Each method then searches the three K from those four
series alone. The twin runs on MODFLOW-NWT, MODFLOW 6 on its structured grid, on a triangle
mesh and on the Voronoi dual of that mesh, and on the Boussinesq solver on the same triangles,
with its PETSc engine and with its default local engine. The truth and the trials of a column
come from the same solver, so the twin tests the recovery on each discretization and not the
solver itself. The Boussinesq trials read the state history of the solver, and the outlet
discharge is the flux through the fixed-head cells. The PETSc leg skips CMA-ES when the ``cma``
package is missing from its environment: the other four runs exercise the forward model alike.
A second test checks that the twin is closed: with the search started at the truth, the cost
and the error are zero on every column.
"""

from __future__ import annotations

import math

import pytest

from tests._helpers.tolerances import tol
from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    TwinCheck,
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from tests.validation.helpers.results import record_case, record_metric
from validation_cases.calibration.shared.solver_variants import (
    checks_for_methods,
    runnable_method_names,
)
from validation_cases.calibration.shared.zero_return import run_twin_at_truth
from validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment import (
    PIECEWISE_K_TWIN_CASES,
)

COST_AT_TRUTH = tol("twin_calibration_closure_noise_free_search_started_at_the_truth")
"""Normalized cost of the trial at the truth: both routes read the same numbers."""

RELATIVE_AT_TRUTH = 1.0e-12
"""The first point of the search is the center of the bounds, exact to a few ulp."""


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow_nwt", id="modflow_nwt", marks=[pytest.mark.nwt, pytest.mark.slow]),
        pytest.param("modflow6", id="modflow6", marks=pytest.mark.mf6),
        pytest.param(
            "modflow6_irregular_tri",
            id="modflow6_irregular_tri",
            marks=[pytest.mark.mf6, pytest.mark.slow],
        ),
        pytest.param(
            "modflow6_voronoi", id="modflow6_voronoi", marks=[pytest.mark.mf6, pytest.mark.slow]
        ),
        pytest.param("boussinesq", id="boussinesq", marks=[pytest.mark.petsc, pytest.mark.slow]),
        pytest.param("boussinesq_local", id="boussinesq_local", marks=pytest.mark.slow),
    ],
)
def test_calibration_twin_boussinesq_fixed_head_piecewise_k_modflow6_benchmark_recovers_truth(
    solver: str,
) -> None:
    """Run the steady piecewise-K twin benchmark and verify zoned K recovery."""
    pytest.importorskip("optuna")
    if solver != "boussinesq":
        pytest.importorskip("cma")

    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )

    definition = PIECEWISE_K_TWIN_CASES[solver]
    methods = runnable_method_names(definition) if solver == "boussinesq" else None
    benchmark = run_lightweight_twin_benchmark_case(
        definition,
        caller_file=__file__,
        method_names=methods,
        checks=checks_for_methods(
            methods,
            {
                "random_search": TwinCheck(meets_target=True, in_distribution=True),
                "scipy_nelder_mead": TwinCheck(best_within=1.5),
                "cma_es": TwinCheck(best_within=5.0, second_smallest_within=2.0),
            },
        ),
    )

    assert benchmark.observations_truth["head_west"]
    assert benchmark.observations_truth["head_middle"]
    assert benchmark.observations_truth["head_east"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == (5 if methods is None else 4)
    random_results = [
        result for result in benchmark.method_results if result.method_name == "random_search"
    ]
    optuna_result = next(
        result for result in benchmark.method_results if result.method_name == "optuna"
    )
    assert len(random_results) == 2
    assert optuna_result.model_distribution_sample_count >= 1
    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_west" in result.param_abs_error
        assert "K_middle" in result.param_abs_error
        assert "K_east" in result.param_abs_error
        assert_lightweight_method_result(result)
    assert all(result.model_distribution_sample_count >= 96 for result in random_results)


@pytest.mark.validation
@pytest.mark.steady
@pytest.mark.fast
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow_nwt", id="modflow_nwt", marks=pytest.mark.nwt),
        pytest.param("modflow6", id="modflow6", marks=pytest.mark.mf6),
        pytest.param(
            "modflow6_irregular_tri",
            id="modflow6_irregular_tri",
            marks=pytest.mark.mf6,
        ),
        pytest.param("modflow6_voronoi", id="modflow6_voronoi", marks=pytest.mark.mf6),
        pytest.param("boussinesq", id="boussinesq", marks=pytest.mark.petsc),
        pytest.param("boussinesq_local", id="boussinesq_local"),
    ],
)
def test_calibration_twin_piecewise_k_noise_free_search_at_the_truth_costs_zero(
    solver: str,
) -> None:
    """A noise-free twin returns to zero: the trial at the truth reads what the truth read."""
    pytest.importorskip("optuna")
    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )

    definition = PIECEWISE_K_TWIN_CASES[solver]
    result = run_twin_at_truth(definition, caller_file=__file__)

    record_case(definition.case_id)
    assert result.cost_best is not None
    record_metric(
        "Best cost of a search started at the truth", result.cost_best, COST_AT_TRUTH, op="<="
    )
    assert result.cost_best <= COST_AT_TRUTH, result.to_mapping()
    for name, truth in definition.truth_params.items():
        relative = result.param_abs_error[name] / float(truth)
        record_metric(
            f"Relative distance of {name} to the truth", relative, RELATIVE_AT_TRUTH, op="<="
        )
        assert relative <= RELATIVE_AT_TRUTH, result.to_mapping()

"""Validation of K and Sy recovery by calibration methods on a transient twin, per solver.

Compared with: the hydraulic conductivity and specific yield that produced the observations.

A run with K = 1e-4 m/s and Sy = 0.10 under a recharge step gives the head at
mid-aquifer and the outlet discharge. Each method then searches K in [5e-5, 3e-4] and Sy in
[0.04, 0.18] from those two series alone. This is the one well-posed two-parameter transient
calibration of the suite: the head series constrains Sy and the discharge series constrains K.
It runs on MODFLOW-NWT, MODFLOW 6 on its structured grid, on a triangle mesh and on the Voronoi
dual of that mesh, and on the Boussinesq solver on the same triangles. The Boussinesq PETSc leg
runs the six methods, minus CMA-ES when the ``cma`` package is missing from its environment. The
default local engine leg is slow, so it runs Nelder-Mead and Optuna, two of the asserted methods.
CMA-ES, Nelder-Mead and Optuna are asserted to land within the case tolerance of the truth
(1.5e-5 on K, 0.04 on Sy). Random search, GP mapping and DA-MH-GP also run; their distances to
the truth are recorded for information and not asserted, because their budget does not
guarantee a hit on a smooth two-parameter surface.
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
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_TWIN_CASES,
)

LOCAL_ENGINE_METHODS = ("scipy_nelder_mead", "optuna")
"""Methods of the default local engine leg: its dense solver takes several seconds per period
series, so two of the asserted methods stand for the six."""

COST_AT_TRUTH = tol("twin_calibration_closure_noise_free_search_started_at_the_truth")
"""Normalized cost of the trial at the truth: both routes read the same numbers."""

RELATIVE_AT_TRUTH = 1.0e-12
"""The first point of the search is the center of the bounds, exact to a few ulp."""


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow_nwt", id="modflow_nwt", marks=[pytest.mark.nwt, pytest.mark.slow]),
        pytest.param("modflow6", id="modflow6", marks=[pytest.mark.mf6, pytest.mark.slow]),
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
def test_calibration_twin_linearized_recharge_step_modflow6_benchmark_recovers_truth(
    solver: str,
) -> None:
    """Run the data-rich transient K+Sy twin and verify the smooth-surface methods recover it."""
    pytest.importorskip("optuna")
    if solver != "boussinesq":
        pytest.importorskip("cma")
    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )

    definition = TRANSIENT_RECHARGE_STEP_TWIN_CASES[solver]
    methods = {
        "boussinesq": runnable_method_names(definition),
        "boussinesq_local": LOCAL_ENGINE_METHODS,
    }.get(solver)
    benchmark = run_lightweight_twin_benchmark_case(
        definition,
        caller_file=__file__,
        method_names=methods,
        checks=checks_for_methods(
            methods,
            {
                "optuna": TwinCheck(best_within=1.0),
                "cma_es": TwinCheck(best_within=1.0),
                "scipy_nelder_mead": TwinCheck(best_within=1.0),
            },
        ),
    )

    assert benchmark.observations_truth["head_mid"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == (6 if methods is None else len(methods))
    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.n_evaluations >= 1
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_global" in result.param_abs_error
        assert "Sy_global" in result.param_abs_error
        assert_lightweight_method_result(result)
    for result in benchmark.method_results:
        if result.method_name in {"random_search", "gp_mapping", "da_mh_gp"}:
            assert result.model_distribution_path is not None
            assert result.model_distribution_path.is_file()


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow_nwt", id="modflow_nwt", marks=[pytest.mark.nwt, pytest.mark.fast]),
        pytest.param("modflow6", id="modflow6", marks=[pytest.mark.mf6, pytest.mark.fast]),
        pytest.param(
            "modflow6_irregular_tri",
            id="modflow6_irregular_tri",
            marks=[pytest.mark.mf6, pytest.mark.fast],
        ),
        pytest.param(
            "modflow6_voronoi", id="modflow6_voronoi", marks=[pytest.mark.mf6, pytest.mark.fast]
        ),
        pytest.param("boussinesq", id="boussinesq", marks=[pytest.mark.petsc, pytest.mark.fast]),
        # The dense local engine takes 28 s on the 60 periods of the truth and three trials.
        pytest.param("boussinesq_local", id="boussinesq_local", marks=pytest.mark.slow),
    ],
)
def test_calibration_twin_linearized_recharge_step_noise_free_search_at_the_truth_costs_zero(
    solver: str,
) -> None:
    """A noise-free transient twin returns to zero: head and flux read the same on both routes."""
    pytest.importorskip("optuna")
    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )

    definition = TRANSIENT_RECHARGE_STEP_TWIN_CASES[solver]
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

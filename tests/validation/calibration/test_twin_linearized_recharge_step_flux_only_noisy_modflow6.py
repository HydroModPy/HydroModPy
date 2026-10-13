"""Wiring smoke test of six calibration methods on a flux-only K+Sy twin, per solver.

Compared with: nothing. It is not a recovery validation. Each method gets 6 evaluations on
noisy outlet discharge alone, so a best point is close to a random draw. The test checks that
every method runs and returns finite costs, that at least one distribution method lands within
tolerance of the truth, and that the point methods stay within 8 times the tolerance. The
distances of the other methods to the truth are information only. It runs on MODFLOW-NWT,
MODFLOW 6 on its structured grid, on a triangle mesh and on the Voronoi dual of that mesh, and on
the Boussinesq solver on the same triangles, with its PETSc engine and its default local engine.
The PETSc leg skips CMA-ES when the ``cma`` package is missing from its environment. The data-rich
twin (``test_twin_linearized_recharge_step_modflow6.py``) is the recovery check.
"""

from __future__ import annotations

import math

import pytest

from tests.regression.golden_utils import assert_required_executables
from tests.validation.calibration.helpers import (
    TwinCheck,
    assert_lightweight_method_result,
    run_lightweight_twin_benchmark_case,
)
from validation_cases.calibration.shared.solver_variants import (
    checks_for_methods,
    runnable_method_names,
)
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASES,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.parametrize(
    "solver",
    [
        pytest.param("modflow_nwt", id="modflow_nwt", marks=[pytest.mark.nwt, pytest.mark.fast]),
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
def test_calibration_twin_linearized_recharge_step_flux_only_noisy_modflow6_wiring_smoke(
    solver: str,
) -> None:
    """Smoke test of the method wiring on a weakly identified flux-only twin, 6 evaluations each."""
    pytest.importorskip("optuna")
    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )

    definition = TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASES[solver]
    methods = runnable_method_names(definition) if solver == "boussinesq" else None
    benchmark = run_lightweight_twin_benchmark_case(
        definition,
        caller_file=__file__,
        method_names=methods,
        evaluation_budget=6,
        checks=checks_for_methods(
            methods,
            {
                "cma_es": TwinCheck(best_within=8.0),
                "scipy_nelder_mead": TwinCheck(best_within=8.0),
            },
        ),
        any_meets_target=("random_search", "optuna", "gp_mapping", "da_mh_gp"),
    )

    assert benchmark.observations_truth["q_east"]
    assert benchmark.observations_used["q_east"]
    assert benchmark.observations_truth != benchmark.observations_used
    assert len(benchmark.method_results) == (6 if methods is None else len(methods))

    distribution_results = [
        result
        for result in benchmark.method_results
        if result.method_name in {"random_search", "optuna", "gp_mapping", "da_mh_gp"}
    ]

    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.iteration_count >= 1
        assert result.n_evaluations >= 1
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert_lightweight_method_result(result)

    assert len(distribution_results) == 4
    for result in distribution_results:
        assert result.model_distribution_path is not None
        assert result.model_distribution_path.is_file()
        assert result.model_distribution_sample_count > 0

    point_methods = {"cma_es", "scipy_nelder_mead"} & (
        set(methods) if methods is not None else {"cma_es", "scipy_nelder_mead"}
    )
    assert sum(
        1 for result in benchmark.method_results if result.method_name in point_methods
    ) == len(point_methods)

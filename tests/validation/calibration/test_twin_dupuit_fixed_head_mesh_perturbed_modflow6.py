"""Validation of scalar K recovery under a mesh mismatch, per solver.

Compared with: the hydraulic conductivity that produced the observations.

The truth runs on a mesh twice as fine as the calibration mesh, so the recovered K carries the
discretization error of the solver. A fixed-head Dupuit strip gives the head at mid-length and
the east outlet discharge. The structured columns (MODFLOW-NWT, MODFLOW 6) compare 80 by 5 cells
with 40 by 5. The triangle column compares a 750-triangle bundle with the 176-triangle bundle of
the analytical case, and the Voronoi column the duals of the two. The two Boussinesq columns, the
PETSc engine and the default local engine, use the same two triangle bundles. The recovery is
asserted within 2.5e-5 m/s of the true 1e-4 m/s. The PETSc leg skips CMA-ES when the ``cma``
package is missing from its environment.
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
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASES,
)


@pytest.mark.validation
@pytest.mark.steady
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
        pytest.param("boussinesq", id="boussinesq", marks=[pytest.mark.petsc, pytest.mark.fast]),
        pytest.param("boussinesq_local", id="boussinesq_local", marks=pytest.mark.slow),
    ],
)
def test_calibration_twin_dupuit_fixed_head_mesh_perturbed_modflow6_recovers_truth_under_mesh_mismatch(
    solver: str,
) -> None:
    """Run the mesh-perturbed steady twin benchmark and verify recovery remains usable."""
    pytest.importorskip("optuna")
    if solver != "boussinesq":
        pytest.importorskip("cma")

    assert_required_executables(
        require_modflow=solver == "modflow_nwt",
        require_modflow6=solver.startswith("modflow6"),
        require_modpath=False,
        require_mt3dms=False,
    )

    definition = STEADY_DUPUIT_MESH_PERTURBED_TWIN_CASES[solver]
    methods = runnable_method_names(definition) if solver == "boussinesq" else None
    benchmark = run_lightweight_twin_benchmark_case(
        definition,
        caller_file=__file__,
        method_names=methods,
        checks=checks_for_methods(
            methods,
            {
                "grid": TwinCheck(meets_target=True, best_within=1.0),
                "scipy_nelder_mead": TwinCheck(meets_target=True, best_within=1.0),
                "cma_es": TwinCheck(meets_target=True, best_within=1.0),
                "random_search": TwinCheck(meets_target=True, in_distribution=True),
                "optuna": TwinCheck(meets_target=True),
            },
        ),
    )

    assert benchmark.simulation_config_path.is_file()
    assert benchmark.truth_simulation_config_path.is_file()
    assert benchmark.simulation_config_path != benchmark.truth_simulation_config_path
    assert benchmark.observations_truth["head_mid"]
    assert benchmark.observations_truth["q_east"]
    assert len(benchmark.method_results) == (5 if methods is None else 4)
    for result in benchmark.method_results:
        assert result.cost_best is not None
        assert math.isfinite(float(result.cost_best)), result.to_mapping()
        assert result.session_prepare_time_seconds is not None
        assert result.mean_candidate_total_time_seconds is not None
        assert result.mean_candidate_preparation_time_seconds is not None
        assert result.mean_candidate_simulation_time_seconds is not None
        assert "K_global" in result.param_abs_error
        assert_lightweight_method_result(result)

    random_result = next(
        result for result in benchmark.method_results if result.method_name == "random_search"
    )
    assert random_result.model_distribution_sample_count >= 1

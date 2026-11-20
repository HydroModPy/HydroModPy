"""Closure check of a twin: a search started at the truth must cost zero.

The truth observations are read from the catalog Run, the trial costs from the
solver files of a lightweight trial. A twin without noise is only closed when
both routes read the same value for the same input: same cell, same
precision, same budget term. The check removes the noise, centers the bounds
on the truth so that the first point of a Nelder-Mead search is the truth, and
runs three evaluations. The best cost and the distance to the truth must then
sit at machine precision on every mesh.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    TwinCalibrationCaseDefinition,
    TwinMethodBenchmarkResult,
)
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case

HALF_WIDTH = 0.5
"""Bounds are ``truth * (1 - HALF_WIDTH)`` to ``truth * (1 + HALF_WIDTH)``."""

EVALUATIONS = 3


def centred_twin_case(definition: TwinCalibrationCaseDefinition) -> TwinCalibrationCaseDefinition:
    """Return ``definition`` with no noise, bounds centered on the truth, one search."""
    if definition.build_truth_simulation_config is not None:
        raise ValueError(
            f"{definition.case_id!r} runs its truth on another mesh, so it cannot return to zero."
        )
    bounds = {
        name: (value * (1.0 - HALF_WIDTH), value * (1.0 + HALF_WIDTH))
        for name, value in definition.truth_params.items()
    }
    # A case id of its own: the benchmark folder is named after it, and the
    # recovery test of the same twin may run beside this check.
    # Nelder-Mead starts at the center of the sampling. A conductivity or a yield is
    # log-uniform unless the target says otherwise, which puts the start at the
    # geometric mean of the bounds. A uniform sampling in the identity search space
    # puts it at their plain mean, the truth.
    targets = {
        name: replace(target, search_space="identity", sampling="uniform")
        for name, target in (definition.parameter_targets or {}).items()
    }
    return replace(
        definition,
        case_id=f"{definition.case_id}_closure",
        parameter_targets=targets,
        bounds=bounds,
        observation_noise=None,
        method_profiles=(
            CalibrationMethodProfile(
                name="scipy_nelder_mead",
                method_kwargs={"max_trials": EVALUATIONS, "xatol": 1.0e-8, "fatol": 1.0e-8},
            ),
        ),
        generate_case_figures=False,
    )


def run_twin_at_truth(
    definition: TwinCalibrationCaseDefinition,
    *,
    caller_file: str | Path,
) -> TwinMethodBenchmarkResult:
    """Run the closure check of one twin and return its single method result."""
    benchmark = run_twin_benchmark_case(
        centred_twin_case(definition),
        caller_file=caller_file,
        case_figures=False,
        evaluation_budget=EVALUATIONS,
    )
    (result,) = benchmark.method_results
    return result

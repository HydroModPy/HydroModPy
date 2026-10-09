"""Shared helpers for lightweight calibration validation tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.validation.helpers.results import record_case, record_metric
from validation_cases.calibration.shared.runtime import run_twin_benchmark_case


def run_lightweight_twin_benchmark_case(
    definition: Any,
    *,
    caller_file: str | Path,
    **kwargs: Any,
):
    """Run one twin benchmark via the v1 :meth:`Project.calibrate` API."""
    benchmark = run_twin_benchmark_case(
        definition,
        caller_file=caller_file,
        case_figures=False,
        **kwargs,
    )
    assert benchmark.summary_path.is_file()
    assert benchmark.configuration_figure is None
    assert benchmark.reference_objective_path is None
    assert benchmark.pruned_artifacts
    record_twin_recovery(benchmark)
    return benchmark


def record_twin_recovery(benchmark: Any) -> None:
    """Record, per method and parameter, the distance to the truth the method is judged on.

    The threshold is the absolute tolerance the case declares for that
    parameter. A ``best_fit`` method is judged on its best candidate, a
    ``distribution`` method on the closest sample of its distribution, and a
    method that accepts either on the smaller of the two.
    """
    definition = benchmark.definition
    record_case(definition.case_id)
    tolerances = dict(definition.parameter_abs_tolerances)
    for result in benchmark.method_results:
        best = dict(result.param_abs_error)
        closest = dict(result.truth_distribution_min_abs_error)
        for name, tolerance in tolerances.items():
            if result.success_metric == "best_fit":
                error, what = best.get(name), "best fit"
            elif result.success_metric == "distribution":
                error, what = closest.get(name), "closest sample"
            else:
                pair = [v for v in (best.get(name), closest.get(name)) if v is not None]
                error, what = (min(pair) if pair else None), "best fit or closest sample"
            if error is not None:
                record_metric(
                    f"{result.method_instance_name}: {what}, distance of {name} to the truth",
                    error,
                    tolerance,
                    op="<=",
                )


def assert_lightweight_method_result(result: Any) -> None:
    """Assert that one lightweight pytest benchmark skipped figure generation."""
    assert result.objective_trace_figure is None
    assert result.objective_landscape_figure is None
    assert result.posterior_distribution_figure is None

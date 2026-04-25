"""Shared helpers for lightweight calibration validation tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from validation_cases.calibration.shared.runtime import run_twin_benchmark_case


def run_lightweight_twin_benchmark_case(
    definition: Any,
    *,
    caller_file: str | Path,
    **kwargs: Any,
):
    """Run one twin benchmark via the v0.6 :meth:`Project.calibrate` API."""
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
    return benchmark


def assert_lightweight_method_result(result: Any) -> None:
    """Assert that one lightweight pytest benchmark skipped figure generation."""
    assert result.objective_trace_figure is None
    assert result.objective_landscape_figure is None
    assert result.posterior_distribution_figure is None

"""Shared runtime helpers for validation cases.

This package hosts the small amount of infrastructure needed both by
``validation_cases`` modules and by the validation tests that exercise them.
It deliberately stays independent from ``tests/`` so analytical cases can be
imported and executed without depending on the test package layout.
"""

from validation_cases.shared.loaders import (
    load_case_config,
    load_case_metadata,
    load_case_tolerances,
    load_field,
    load_last_npy_array,
    load_last_npy_array_on_expected_grid,
    load_npy_time_series_arrays,
    load_time_series_fields,
    merge_case_flow_section,
)
from validation_cases.shared.cli import (
    apply_output_root_override,
    build_run_case_parser,
    print_run_case_summary,
    resolve_output_png,
    run_case_main,
)
from validation_cases.shared.metrics import (
    max_abs_error,
    max_std_along_axis,
    mean_along_axis,
    rmse,
)
from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
    run_launcher_validation_case,
)

__all__ = [
    "ValidationRunResult",
    "apply_output_root_override",
    "build_run_case_parser",
    "load_case_config",
    "load_case_metadata",
    "load_case_tolerances",
    "load_field",
    "load_last_npy_array",
    "load_last_npy_array_on_expected_grid",
    "load_npy_time_series_arrays",
    "max_abs_error",
    "max_std_along_axis",
    "mean_along_axis",
    "merge_case_flow_section",
    "print_run_case_summary",
    "resolve_output_png",
    "resolve_validation_results_dir",
    "rmse",
    "run_case_main",
    "run_launcher_validation_case",
]

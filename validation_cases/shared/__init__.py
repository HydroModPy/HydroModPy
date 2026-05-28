"""Shared runtime helpers for validation cases.

This package hosts the small amount of infrastructure needed both by
``validation_cases`` modules and by the validation tests that exercise them.
It deliberately stays independent from ``tests/`` so analytical cases can be
imported and executed without depending on the test package layout.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "ValidationRunResult": "validation_cases.shared.runtime",
    "align_snapshot_series_to_expected_count": "validation_cases.shared.loaders",
    "apply_output_root_override": "validation_cases.shared.cli",
    "build_run_case_parser": "validation_cases.shared.cli",
    "load_case_config": "validation_cases.shared.loaders",
    "load_case_metadata": "validation_cases.shared.loaders",
    "load_case_tolerances": "validation_cases.shared.loaders",
    "load_field": "validation_cases.shared.loaders",
    "load_field_on_expected_grid": "validation_cases.shared.loaders",
    "load_last_npy_array": "validation_cases.shared.loaders",
    "load_npy_dict": "validation_cases.shared.loaders",
    "load_npy_time_series_arrays": "validation_cases.shared.loaders",
    "load_time_series_fields": "validation_cases.shared.loaders",
    "max_abs_error": "validation_cases.shared.metrics",
    "max_std_along_axis": "validation_cases.shared.metrics",
    "mean_along_axis": "validation_cases.shared.metrics",
    "merge_case_flow_section": "validation_cases.shared.loaders",
    "print_run_case_summary": "validation_cases.shared.cli",
    "resolve_output_png": "validation_cases.shared.cli",
    "resolve_validation_results_dir": "validation_cases.shared.runtime",
    "rmse": "validation_cases.shared.metrics",
    "run_case_main": "validation_cases.shared.cli",
    "run_launcher_validation_case": "validation_cases.shared.runtime",
    "write_validation_fields_to_store": "validation_cases.shared.runtime",
}

__all__ = tuple(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value

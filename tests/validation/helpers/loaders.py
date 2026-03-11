"""Backward-compatible wrappers around ``validation_cases.shared.loaders``."""

from validation_cases.shared.loaders import (
    load_case_metadata,
    load_case_tolerances,
    load_last_npy_array,
    load_npy_time_series_arrays,
)

__all__ = [
    "load_case_metadata",
    "load_case_tolerances",
    "load_last_npy_array",
    "load_npy_time_series_arrays",
]

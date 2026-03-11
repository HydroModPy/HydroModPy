"""Backward-compatible wrappers around ``validation_cases.shared.metrics``."""

from validation_cases.shared.metrics import (
    max_abs_error,
    max_std_along_axis,
    mean_along_axis,
    rmse,
)

__all__ = [
    "max_abs_error",
    "max_std_along_axis",
    "mean_along_axis",
    "rmse",
]

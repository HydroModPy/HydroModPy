"""Backward-compatible wrappers around ``validation_cases.shared.runtime``."""

from validation_cases.shared.runtime import (
    ValidationRunResult,
    resolve_validation_results_dir,
    run_launcher_validation_case,
)

__all__ = [
    "ValidationRunResult",
    "resolve_validation_results_dir",
    "run_launcher_validation_case",
]

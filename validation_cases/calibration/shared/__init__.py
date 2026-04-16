"""Shared helpers for calibration inverse-validation cases."""

from validation_cases.calibration.shared.definitions import (
    CalibrationMethodProfile,
    TwinCalibrationBenchmarkResult,
    TwinCalibrationCaseDefinition,
    TwinMethodBenchmarkResult,
)

__all__ = [
    "CalibrationMethodProfile",
    "TwinCalibrationBenchmarkResult",
    "TwinCalibrationCaseDefinition",
    "TwinMethodBenchmarkResult",
    "run_twin_benchmark_case",
]


def __getattr__(name: str):
    if name == "run_twin_benchmark_case":
        from validation_cases.calibration.shared.runtime import run_twin_benchmark_case

        return run_twin_benchmark_case
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

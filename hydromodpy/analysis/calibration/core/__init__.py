"""Core calibration abstractions (engine, parameters, objective, results)."""

from __future__ import annotations

import importlib
from typing import Any


_LAZY_EXPORTS = {
    "CalibrationEngine": "hydromodpy.analysis.calibration.core.engine",
    "CalibrationParameterSet": "hydromodpy.analysis.calibration.core.parameters",
    "CalibrationResults": "hydromodpy.analysis.calibration.core.results",
    "CompositeBlockEvaluation": (
        "hydromodpy.analysis.calibration.core.composite_objective"
    ),
    "CompositeObjective": "hydromodpy.analysis.calibration.core.composite_objective",
    "CompositeObjectiveBlock": (
        "hydromodpy.analysis.calibration.core.composite_objective"
    ),
    "CompositeObjectiveEvaluation": (
        "hydromodpy.analysis.calibration.core.composite_objective"
    ),
    "ObjectiveFunction": "hydromodpy.analysis.calibration.core.objective_function",
}


def __getattr__(name: str) -> Any:
    """Load public calibration-core symbols on first access."""
    if name in _LAZY_EXPORTS:
        module = importlib.import_module(_LAZY_EXPORTS[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'hydromodpy.analysis.calibration.core' has no attribute {name!r}"
    )


__all__ = (
    "CalibrationEngine",
    "CalibrationParameterSet",
    "CalibrationResults",
    "CompositeBlockEvaluation",
    "CompositeObjective",
    "CompositeObjectiveBlock",
    "CompositeObjectiveEvaluation",
    "ObjectiveFunction",
)

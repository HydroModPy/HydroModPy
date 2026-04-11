"""Core calibration abstractions (engine, parameters, objective, results)."""

from hydromodpy.analysis.calibration.core.composite_objective import (
    CompositeBlockEvaluation,
    CompositeObjective,
    CompositeObjectiveBlock,
    CompositeObjectiveEvaluation,
)
from hydromodpy.analysis.calibration.core.engine import CalibrationEngine
from hydromodpy.analysis.calibration.core.objective_function import ObjectiveFunction
from hydromodpy.analysis.calibration.core.parameters import CalibrationParameterSet
from hydromodpy.analysis.calibration.core.results import CalibrationResults

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
